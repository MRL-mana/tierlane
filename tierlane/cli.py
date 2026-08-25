"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import Config, ConfigError, load_config
from .guards import (
    CloudEgressBlocked,
    PathNotAllowed,
    SecretDetected,
    read_files,
    resolve,
)
from .router import Result, is_child, pick_tier, run, run_with_escalation, should_hold

__all__ = ["main"]

HOLD_MESSAGE = (
    "Held. This task matches a `hold` keyword, so it was not delegated — "
    "handle it yourself."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tierlane",
        description=(
            "Route a task to the cheapest AI CLI that can handle it, and keep "
            "your files off third-party clouds unless you say otherwise."
        ),
    )
    parser.add_argument("task", help="What you want done.")
    parser.add_argument(
        "--tier", type=int, default=None,
        help="Force a tier instead of choosing one from the task text.",
    )
    parser.add_argument(
        "--files", nargs="*", default=[],
        help="Files to include as context. These are scanned for secrets first.",
    )
    parser.add_argument(
        "--allow-cloud", action="store_true",
        help="Permit sending file contents to a cloud-backed tier.",
    )
    parser.add_argument(
        "--allow-root", action="append", default=[],
        help="Add a directory that --files may read from. Repeatable.",
    )
    parser.add_argument(
        "--escalate", action="store_true",
        help="Step up a tier when a result errors or comes back too short.",
    )
    parser.add_argument(
        "--max-tier", type=int, default=None,
        help="Ceiling for --escalate.",
    )
    parser.add_argument(
        "--min-output-chars", type=int, default=None,
        help="Below this length, --escalate treats a result as inadequate.",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Per-tier timeout in seconds.")
    parser.add_argument("--config", default=None, help="Path to tierlane.toml.")
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show the routing decision without running anything.",
    )
    return parser


def _dry_run(task: str, level: int, config: Config, args, context: str) -> dict:
    tier = config.tier(level)
    return {
        "mode": "dry-run",
        "task": task,
        "config": str(config.source) if config.source else None,
        "selected_tier": level,
        "tier_name": tier.name,
        "kind": tier.kind,
        "cloud": tier.cloud,
        "available": tier.available,
        "would_send_files": bool(context),
        "blocked": tier.cloud and bool(context) and not args.allow_cloud,
        "context_chars": len(context),
        "tiers": [
            {
                "level": t.level,
                "name": t.name,
                "cloud": t.cloud,
                "available": t.available,
            }
            for t in (config.tier(lvl) for lvl in config.levels)
        ],
    }


def _render(result: Result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    skipped = [a for a in result.attempts if not a.ok and a.elapsed == 0.0]
    for attempt in skipped:
        print(f"[tierlane] skipped tier {attempt.level} ({attempt.name}): {attempt.detail}",
              file=sys.stderr)

    header = f"[tierlane → {result.tier_name}] {result.elapsed:.1f}s"
    if len(result.attempts) > 1:
        header += f" · {len(result.attempts)} attempts"
    print(header, file=sys.stderr)
    print(result.output)


async def _main_async(args: argparse.Namespace, config: Config) -> int:
    if should_hold(args.task, config):
        print(HOLD_MESSAGE, file=sys.stderr)
        return 2

    roots = list(config.read_roots) + [resolve(r) for r in args.allow_root]
    context = read_files(args.files, roots, config.max_context_chars) if args.files else ""

    level = args.tier if args.tier is not None else pick_tier(args.task, config)

    # A nested run means some backend invoked tierlane again. Pin it to the
    # cheapest tier and switch escalation off so the chain cannot climb.
    if is_child():
        print("[tierlane] running as a child process — pinned to the cheapest tier.",
              file=sys.stderr)
        level = min(config.tiers)
        args.escalate = False

    if args.dry_run:
        print(json.dumps(_dry_run(args.task, level, config, args, context),
                         ensure_ascii=False, indent=2))
        return 0

    if args.escalate:
        result = await run_with_escalation(
            args.task, level, config,
            context=context,
            allow_cloud=args.allow_cloud,
            timeout=args.timeout,
            max_level=args.max_tier,
            min_output_chars=args.min_output_chars,
        )
    else:
        result = await run(
            args.task, level, config,
            context=context,
            allow_cloud=args.allow_cloud,
            timeout=args.timeout,
        )

    _render(result, args.json)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[tierlane] config error: {exc}", file=sys.stderr)
        return 3

    try:
        return asyncio.run(_main_async(args, config))
    except (SecretDetected, PathNotAllowed, CloudEgressBlocked) as exc:
        print(f"[tierlane] blocked: {exc}", file=sys.stderr)
        return 4
    except ConfigError as exc:
        print(f"[tierlane] config error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\n[tierlane] interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

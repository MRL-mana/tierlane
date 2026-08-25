"""Tier selection and task execution, including escalation."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .backends import CHILD_ENV_VAR, BackendError, run_tier
from .config import Config, Tier
from .guards import CloudEgressBlocked, check_egress

__all__ = ["Result", "Attempt", "pick_tier", "should_hold", "run", "run_with_escalation"]


@dataclass
class Attempt:
    level: int
    name: str
    ok: bool
    elapsed: float
    detail: str = ""


@dataclass
class Result:
    task: str
    level: int
    tier_name: str
    output: str
    ok: bool
    elapsed: float
    attempts: list[Attempt] = field(default_factory=list)
    held: bool = False

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "tier": self.level,
            "tier_name": self.tier_name,
            "output": self.output,
            "ok": self.ok,
            "held": self.held,
            "elapsed_seconds": round(self.elapsed, 2),
            "attempts": [
                {
                    "tier": a.level,
                    "name": a.name,
                    "ok": a.ok,
                    "elapsed_seconds": round(a.elapsed, 2),
                    "detail": a.detail,
                }
                for a in self.attempts
            ],
        }


def is_child() -> bool:
    """True when this process was spawned by another tierlane run."""
    return os.getenv(CHILD_ENV_VAR, "") == "1"


def should_hold(task: str, config: Config) -> bool:
    """Whether the task is one the caller said never to delegate."""
    lowered = task.lower()
    return any(keyword in lowered for keyword in config.hold_keywords)


def pick_tier(task: str, config: Config) -> int:
    """Choose a tier from the task text.

    Rules are pre-sorted highest-tier-first by the config loader, so a task that
    matches several rules gets the most capable backend among them. Anything
    unmatched falls to the cheapest tier defined.
    """
    lowered = task.lower()
    for level, keywords in config.rules:
        if any(keyword in lowered for keyword in keywords):
            return level
    return min(config.tiers)


def _compose(task: str, context: str) -> str:
    if not context:
        return task
    return f"{task}\n\nReference context:\n{context}"


async def run(
    task: str,
    level: int,
    config: Config,
    *,
    context: str = "",
    allow_cloud: bool = False,
    timeout: float | None = None,
) -> Result:
    """Run `task` on exactly one tier."""
    tier: Tier = config.tier(level)
    check_egress(is_cloud=tier.cloud, has_files=bool(context), allow_cloud=allow_cloud)

    started = time.monotonic()
    try:
        output = await run_tier(tier, _compose(task, context), timeout or config.timeout)
        ok = True
        detail = ""
    except BackendError as exc:
        output = str(exc)
        ok = False
        detail = str(exc)

    elapsed = time.monotonic() - started
    return Result(
        task=task,
        level=level,
        tier_name=tier.name,
        output=output,
        ok=ok,
        elapsed=elapsed,
        attempts=[Attempt(level, tier.name, ok, elapsed, detail)],
    )


async def run_with_escalation(
    task: str,
    level: int,
    config: Config,
    *,
    context: str = "",
    allow_cloud: bool = False,
    timeout: float | None = None,
    max_level: int | None = None,
    min_output_chars: int | None = None,
) -> Result:
    """Run `task`, stepping up a tier whenever the result looks inadequate.

    "Inadequate" means the backend errored, or returned less text than
    `min_output_chars`. That threshold is configurable because a task like
    "answer with just the number" produces a correct three-character answer
    that would otherwise be failed upward into a paid tier.
    """
    ceiling = config.max_level if max_level is None else max_level
    floor = min_output_chars if min_output_chars is not None else config.min_output_chars
    has_files = bool(context)

    attempts: list[Attempt] = []
    last: Result | None = None

    for candidate in [lvl for lvl in config.levels if level <= lvl <= ceiling]:
        tier = config.tier(candidate)

        # A blocked cloud tier is skipped rather than fatal: the run continues
        # up the ladder, and any local result already obtained is preserved.
        try:
            check_egress(
                is_cloud=tier.cloud, has_files=has_files, allow_cloud=allow_cloud
            )
        except CloudEgressBlocked as exc:
            attempts.append(Attempt(candidate, tier.name, False, 0.0, str(exc)))
            continue

        result = await run(
            task,
            candidate,
            config,
            context=context,
            allow_cloud=allow_cloud,
            timeout=timeout,
        )
        attempts.extend(result.attempts)
        last = result

        if result.ok and len(result.output.strip()) >= floor:
            result.attempts = attempts
            return result

    if last is None:
        return Result(
            task=task,
            level=level,
            tier_name="none",
            output="No tier was eligible to run this task.",
            ok=False,
            elapsed=0.0,
            attempts=attempts,
        )

    last.attempts = attempts
    return last

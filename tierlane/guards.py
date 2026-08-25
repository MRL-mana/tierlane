"""Safety guards: secret scanning, path sandboxing, and cloud egress control.

These run *before* a task is handed to any backend. The ordering matters:
a file is scanned in full before it is truncated to fit the context budget,
so nothing can slip past the scanner by living past the cut-off point.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "SECRET_PATTERNS",
    "SecretDetected",
    "PathNotAllowed",
    "CloudEgressBlocked",
    "contains_secret",
    "find_secret",
    "resolve",
    "within",
    "read_files",
    "check_egress",
]


# Patterns for credentials that must never leave the machine. Each is anchored
# on a vendor-specific prefix rather than generic entropy, which keeps false
# positives low enough that people leave the scanner switched on.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("OpenAI key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "Inline credential",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
            r"['\"][A-Za-z0-9_\-/+]{16,}['\"]"
        ),
    ),
)


class SecretDetected(Exception):
    """A file contained something that looks like a live credential."""


class PathNotAllowed(Exception):
    """A file was requested from outside the configured read roots."""


class CloudEgressBlocked(Exception):
    """A cloud tier was selected while carrying file contents, without consent."""


def find_secret(text: str) -> str | None:
    """Return the name of the first secret kind found, or None."""
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return label
    return None


def contains_secret(text: str) -> bool:
    return find_secret(text) is not None


def resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def within(path: Path, roots: list[Path]) -> bool:
    """True when `path` is one of `roots` or lives underneath one."""
    return any(path == root or root in path.parents for root in roots)


def read_files(
    paths: list[str],
    roots: list[Path],
    max_chars: int,
) -> str:
    """Read files into a single line-numbered context block.

    Raises PathNotAllowed for anything outside `roots`, and SecretDetected if a
    credential pattern matches. The secret scan deliberately runs against the
    whole file, before truncation, so a key sitting past `max_chars` still
    blocks the send instead of being silently dropped from the payload.
    """
    chunks: list[str] = []
    total = 0

    for raw in paths:
        target = resolve(raw)
        if not within(target, roots):
            raise PathNotAllowed(
                f"{target} is outside the allowed read roots. "
                f"Pass --allow-root to widen them."
            )
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            chunks.append(f"# [{raw}] could not be read: {exc}")
            continue

        numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        block = f"# ===== {target} =====\n{numbered}"

        label = find_secret(block)
        if label is not None:
            raise SecretDetected(f"{label} found in {target} — refusing to send it.")

        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                chunks.append(block[:remaining] + "\n…(truncated)")
            break

        chunks.append(block)
        total += len(block)

    return "\n\n".join(chunks)


def check_egress(*, is_cloud: bool, has_files: bool, allow_cloud: bool) -> None:
    """Gate a cloud backend that is about to carry file contents off the machine.

    A bare task string is written by whoever invoked the router, so they already
    know what it says. File contents are different: they are pulled in by the
    tool and can hold code the caller never looked at. Only that second case
    requires explicit consent.
    """
    if is_cloud and has_files and not allow_cloud:
        raise CloudEgressBlocked(
            "This tier sends your file contents to a third-party cloud API. "
            "Re-run with --allow-cloud if that is what you want."
        )

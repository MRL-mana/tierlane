"""tierlane — route AI tasks to the cheapest CLI that can handle them.

The two things this does that a plain shell alias cannot:

1. Picks a backend from the task text, so cheap work stops reaching expensive
   models by default.
2. Refuses to hand your file contents to a third-party cloud unless you say so,
   and scans those files for credentials before anything is sent.
"""

from __future__ import annotations

from .config import Config, ConfigError, Tier, load_config
from .guards import (
    CloudEgressBlocked,
    PathNotAllowed,
    SecretDetected,
    contains_secret,
    find_secret,
    read_files,
)
from .router import Result, pick_tier, run, run_with_escalation, should_hold

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Config",
    "ConfigError",
    "Tier",
    "load_config",
    "Result",
    "pick_tier",
    "run",
    "run_with_escalation",
    "should_hold",
    "read_files",
    "contains_secret",
    "find_secret",
    "SecretDetected",
    "PathNotAllowed",
    "CloudEgressBlocked",
]

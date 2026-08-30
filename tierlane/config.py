"""Configuration: tiers, routing rules, and where they are loaded from.

Everything about *which* CLIs exist lives in a TOML file rather than in code,
so adding a backend never means editing the router.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Tier", "Config", "ConfigError", "load_config", "default_config_path"]

CONFIG_FILENAME = "tierlane.toml"


class ConfigError(Exception):
    """The config file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Tier:
    """One backend the router can hand a task to.

    kind="cli"  -> `command` is run as a subprocess.
    kind="http" -> `endpoint` is called with an OpenAI-compatible chat payload.
    """

    level: int
    name: str
    kind: str
    cloud: bool = False
    description: str = ""
    command: list[str] = field(default_factory=list)
    endpoint: str = ""
    model: str = ""

    @property
    def executable(self) -> str | None:
        return self.command[0] if self.command else None

    @property
    def available(self) -> bool:
        """Whether this tier can actually run on this machine right now."""
        if self.kind == "http":
            return bool(self.endpoint)
        exe = self.executable
        return bool(exe) and shutil.which(exe) is not None


@dataclass(frozen=True)
class Config:
    tiers: dict[int, Tier]
    rules: list[tuple[int, list[str]]]
    hold_keywords: list[str]
    read_roots: list[Path]
    max_context_chars: int
    timeout: float
    min_output_chars: int
    source: Path | None = None

    def tier(self, level: int) -> Tier:
        try:
            return self.tiers[level]
        except KeyError:
            known = ", ".join(str(k) for k in sorted(self.tiers))
            raise ConfigError(f"No tier {level} is defined. Known tiers: {known}") from None

    @property
    def levels(self) -> list[int]:
        return sorted(self.tiers)

    @property
    def max_level(self) -> int:
        return max(self.tiers) if self.tiers else 0


def default_config_path() -> Path | None:
    """Find a config file, nearest first.

    Order: $TIERLANE_CONFIG, ./tierlane.toml, then the user config directory.
    """
    override = os.getenv("TIERLANE_CONFIG")
    if override:
        return Path(override).expanduser()

    local = Path.cwd() / CONFIG_FILENAME
    if local.is_file():
        return local

    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    user = base / "tierlane" / CONFIG_FILENAME
    return user if user.is_file() else None


def _parse_tiers(raw: list[dict]) -> dict[int, Tier]:
    tiers: dict[int, Tier] = {}
    for entry in raw:
        if "level" not in entry:
            raise ConfigError(f"A [[tier]] entry is missing `level`: {entry}")
        level = entry["level"]
        if level in tiers:
            raise ConfigError(f"Tier level {level} is defined twice.")

        kind = entry.get("kind", "cli")
        if kind not in ("cli", "http"):
            raise ConfigError(f"Tier {level}: kind must be 'cli' or 'http', got {kind!r}.")
        if kind == "cli" and not entry.get("command"):
            raise ConfigError(f"Tier {level}: kind='cli' requires a `command` list.")
        if kind == "http" and not entry.get("endpoint"):
            raise ConfigError(f"Tier {level}: kind='http' requires an `endpoint`.")

        tiers[level] = Tier(
            level=level,
            name=entry.get("name", f"tier-{level}"),
            kind=kind,
            cloud=bool(entry.get("cloud", False)),
            description=entry.get("description", ""),
            command=list(entry.get("command", [])),
            endpoint=entry.get("endpoint", ""),
            model=entry.get("model", ""),
        )

    if not tiers:
        raise ConfigError("No [[tier]] entries found — there is nothing to route to.")
    return tiers


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate a config file."""
    resolved = Path(path).expanduser() if path else default_config_path()
    if resolved is None:
        raise ConfigError(
            f"No {CONFIG_FILENAME} found. Create one in this directory "
            f"with `tierlane init`, or set TIERLANE_CONFIG."
        )
    if not resolved.is_file():
        raise ConfigError(f"Config file not found: {resolved}")

    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{resolved} is not valid TOML: {exc}") from exc

    tiers = _parse_tiers(data.get("tier", []))

    rules: list[tuple[int, list[str]]] = []
    for entry in data.get("rule", []):
        if "tier" not in entry:
            raise ConfigError(f"A [[rule]] entry is missing `tier`: {entry}")
        level = entry["tier"]
        if level not in tiers:
            raise ConfigError(f"A [[rule]] points at tier {level}, which is not defined.")
        keywords = [str(k).lower() for k in entry.get("keywords", [])]
        if keywords:
            rules.append((level, keywords))

    # Highest tier first, so a task naming both "draft" and "architecture"
    # lands on the more capable backend rather than the cheaper one.
    rules.sort(key=lambda pair: pair[0], reverse=True)

    defaults = data.get("defaults", {})
    roots = [Path(r).expanduser().resolve() for r in defaults.get("read_roots", ["."])]

    return Config(
        tiers=tiers,
        rules=rules,
        hold_keywords=[str(k).lower() for k in data.get("hold", {}).get("keywords", [])],
        read_roots=roots,
        max_context_chars=int(defaults.get("max_context_chars", 12000)),
        timeout=float(defaults.get("timeout", 300)),
        min_output_chars=int(defaults.get("min_output_chars", 50)),
        source=resolved,
    )

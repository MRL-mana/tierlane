"""Tier selection, config validation, and escalation behaviour."""

from __future__ import annotations

import asyncio
import textwrap

import pytest

from tierlane.config import ConfigError, load_config
from tierlane.router import pick_tier, run_with_escalation, should_hold

BASE_CONFIG = """
[defaults]
read_roots = ["."]
min_output_chars = 10

[[tier]]
level = 0
name = "local"
kind = "http"
endpoint = "http://127.0.0.1:11434/v1/chat/completions"
model = "test"
cloud = false

[[tier]]
level = 1
name = "flash"
kind = "cli"
command = ["echo", "{prompt}"]
cloud = true

[[tier]]
level = 2
name = "review"
kind = "cli"
command = ["echo", "{prompt}"]
cloud = true

[[rule]]
tier = 0
keywords = ["draft", "translate"]

[[rule]]
tier = 1
keywords = ["summarize", "compare"]

[[rule]]
tier = 2
keywords = ["review", "design"]

[hold]
keywords = ["deploy", "delete"]
"""


def write_config(tmp_path, body: str = BASE_CONFIG):
    path = tmp_path / "tierlane.toml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return load_config(path)


# ─── config validation ────────────────────────────────────────────────────

def test_a_config_with_no_tiers_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="nothing to route to"):
        write_config(tmp_path, "[defaults]\n")


def test_duplicate_tier_levels_are_rejected(tmp_path):
    body = """
    [[tier]]
    level = 0
    name = "a"
    kind = "cli"
    command = ["echo"]

    [[tier]]
    level = 0
    name = "b"
    kind = "cli"
    command = ["echo"]
    """
    with pytest.raises(ConfigError, match="defined twice"):
        write_config(tmp_path, body)


def test_a_cli_tier_without_a_command_is_rejected(tmp_path):
    body = """
    [[tier]]
    level = 0
    name = "broken"
    kind = "cli"
    """
    with pytest.raises(ConfigError, match="requires a `command`"):
        write_config(tmp_path, body)


def test_a_rule_pointing_at_an_undefined_tier_is_rejected(tmp_path):
    body = """
    [[tier]]
    level = 0
    name = "only"
    kind = "cli"
    command = ["echo"]

    [[rule]]
    tier = 9
    keywords = ["whatever"]
    """
    with pytest.raises(ConfigError, match="tier 9"):
        write_config(tmp_path, body)


def test_asking_for_an_undefined_tier_names_the_ones_that_exist(tmp_path):
    config = write_config(tmp_path)
    with pytest.raises(ConfigError, match="0, 1, 2"):
        config.tier(7)


# ─── tier selection ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "task, expected",
    [
        ("draft a changelog entry", 0),
        ("summarize this module", 1),
        ("review the error handling", 2),
        ("something with no keywords at all", 0),
    ],
)
def test_tier_is_chosen_from_the_task_text(tmp_path, task, expected):
    assert pick_tier(task, write_config(tmp_path)) == expected


def test_the_highest_matching_tier_wins(tmp_path):
    """A task naming cheap and expensive work should get the capable backend."""
    config = write_config(tmp_path)
    assert pick_tier("draft and review the design", config) == 2


def test_matching_is_case_insensitive(tmp_path):
    assert pick_tier("REVIEW this", write_config(tmp_path)) == 2


# ─── hold list ────────────────────────────────────────────────────────────

def test_hold_keywords_stop_delegation(tmp_path):
    config = write_config(tmp_path)
    assert should_hold("deploy to production", config)
    assert should_hold("DELETE the old rows", config)


def test_ordinary_tasks_are_not_held(tmp_path):
    assert not should_hold("summarize the readme", write_config(tmp_path))


# ─── escalation ───────────────────────────────────────────────────────────

def test_escalation_skips_blocked_cloud_tiers_instead_of_aborting(tmp_path):
    """Carrying files without --allow-cloud should step past cloud tiers.

    Every tier here is either unreachable (no Ollama in CI) or cloud-gated, so
    the run must end with a normal failed Result rather than raising.
    """
    config = write_config(tmp_path)

    result = asyncio.run(
        run_with_escalation(
            "summarize this",
            0,
            config,
            context="# ===== f.py =====\n1: x = 1",
            allow_cloud=False,
            timeout=5,
        )
    )

    assert not result.ok
    skipped = [a for a in result.attempts if "cloud" in a.detail.lower()]
    assert skipped, "cloud tiers should be recorded as skipped, not silently dropped"
    assert {a.level for a in skipped} == {1, 2}


def test_a_bare_task_is_not_gated_during_escalation(tmp_path):
    """With no files attached, cloud tiers run rather than being skipped."""
    config = write_config(tmp_path)

    result = asyncio.run(
        run_with_escalation("summarize this", 1, config, allow_cloud=False, timeout=10)
    )

    gated = [a for a in result.attempts if "allow-cloud" in a.detail]
    assert not gated

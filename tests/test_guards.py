"""Guards are the part that has to be right, so they get the most tests."""

from __future__ import annotations

import pytest

from tierlane.guards import (
    CloudEgressBlocked,
    PathNotAllowed,
    SecretDetected,
    check_egress,
    contains_secret,
    find_secret,
    read_files,
    within,
)


# ─── secret detection ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sample, expected",
    [
        ("ghp_" + "a" * 36, "GitHub token"),
        ("xoxb-123456789012-abcdef", "Slack token"),
        ("sk-" + "A" * 32, "OpenAI key"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----", "Private key"),
        ("AIza" + "b" * 35, "Google API key"),
        ("AKIA" + "C" * 16, "AWS access key"),
        ("https://hooks.slack.com/services/T00/B00/xyz", "Slack webhook"),
        ('api_key = "' + "d" * 20 + '"', "Inline credential"),
    ],
)
def test_known_credentials_are_detected(sample: str, expected: str) -> None:
    assert find_secret(sample) == expected


@pytest.mark.parametrize(
    "sample",
    [
        "def add(a, b): return a + b",
        "# the token is passed to the parser",
        "password_field.set_placeholder('enter a password')",
        "sk-short",
        "",
    ],
)
def test_ordinary_code_is_not_flagged(sample: str) -> None:
    assert not contains_secret(sample)


# ─── path sandboxing ──────────────────────────────────────────────────────

def test_within_accepts_the_root_itself(tmp_path):
    assert within(tmp_path, [tmp_path])


def test_within_accepts_a_nested_path(tmp_path):
    nested = tmp_path / "a" / "b" / "c.py"
    assert within(nested, [tmp_path])


def test_within_rejects_a_sibling(tmp_path):
    root = tmp_path / "allowed"
    other = tmp_path / "elsewhere" / "secret.py"
    assert not within(other, [root])


def test_read_files_rejects_paths_outside_the_roots(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('hi')", encoding="utf-8")

    with pytest.raises(PathNotAllowed):
        read_files([str(outside)], [allowed], max_chars=10_000)


# ─── reading ──────────────────────────────────────────────────────────────

def test_read_files_numbers_the_lines(tmp_path):
    target = tmp_path / "sample.py"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    body = read_files([str(target)], [tmp_path], max_chars=10_000)

    assert "1: alpha" in body
    assert "2: beta" in body


def test_read_files_truncates_at_the_budget(tmp_path):
    target = tmp_path / "big.py"
    target.write_text("x = 1\n" * 2000, encoding="utf-8")

    body = read_files([str(target)], [tmp_path], max_chars=1000)

    assert len(body) <= 1100
    assert "truncated" in body


def test_a_secret_past_the_truncation_point_still_blocks_the_send(tmp_path):
    """The scan must see the whole file, not just the part that would be sent.

    Otherwise a key sitting beyond max_chars is dropped from the payload by
    truncation and never scanned — which looks safe but means the guard simply
    stopped looking.
    """
    target = tmp_path / "long.py"
    target.write_text("filler = 1\n" * 500 + 'api_key = "' + "z" * 24 + '"\n',
                      encoding="utf-8")

    with pytest.raises(SecretDetected):
        read_files([str(target)], [tmp_path], max_chars=200)


def test_unreadable_files_are_reported_not_fatal(tmp_path):
    missing = tmp_path / "gone.py"
    body = read_files([str(missing)], [tmp_path], max_chars=10_000)
    assert "could not be read" in body


# ─── cloud egress ─────────────────────────────────────────────────────────

def test_a_bare_task_may_go_to_the_cloud_without_consent():
    """The task string was written by the caller, so they already know it."""
    check_egress(is_cloud=True, has_files=False, allow_cloud=False)


def test_file_contents_are_blocked_without_consent():
    with pytest.raises(CloudEgressBlocked):
        check_egress(is_cloud=True, has_files=True, allow_cloud=False)


def test_file_contents_pass_once_consent_is_given():
    check_egress(is_cloud=True, has_files=True, allow_cloud=True)


def test_local_tiers_are_never_gated():
    check_egress(is_cloud=False, has_files=True, allow_cloud=False)

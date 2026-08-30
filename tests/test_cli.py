"""CLI setup behavior that must work after an installed-package launch."""

from __future__ import annotations

import pytest

from tierlane.cli import main
from tierlane.config import load_config
from tierlane import __version__


def test_package_version_matches_release():
    assert __version__ == "0.3.0"


def test_version_flag_reports_the_release(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "tierlane 0.3.0"


def test_init_creates_a_valid_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["init"]) == 0

    target = tmp_path / "tierlane.toml"
    assert target.is_file()
    config = load_config(target)
    assert config.levels == [0, 1, 2, 3]
    assert config.tier(0).cloud is False
    assert config.tier(1).cloud is True
    assert "created tierlane.toml" in capsys.readouterr().out


def test_init_refuses_to_overwrite_an_existing_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "tierlane.toml"
    target.write_text("keep me", encoding="utf-8")

    assert main(["init"]) == 3

    assert target.read_text(encoding="utf-8") == "keep me"
    assert "already exists" in capsys.readouterr().err


def test_init_can_write_to_an_explicit_nested_path(tmp_path):
    target = tmp_path / "config" / "tierlane.toml"

    assert main(["init", "--output", str(target)]) == 0

    assert target.is_file()
    assert load_config(target).levels == [0, 1, 2, 3]


def test_doctor_reports_missing_commands_without_calling_them(tmp_path, capsys):
    config = tmp_path / "tierlane.toml"
    config.write_text(
        """
[[tier]]
level = 0
name = "local-http"
kind = "http"
endpoint = "http://127.0.0.1:9999/v1/chat/completions"
cloud = false

[[tier]]
level = 1
name = "missing-cli"
kind = "cli"
command = ["__tierlane_command_that_does_not_exist__"]
cloud = true
""".strip(),
        encoding="utf-8",
    )

    assert main(["doctor", "--config", str(config)]) == 0

    output = capsys.readouterr().out
    assert "[configured] tier 0 local-http" in output
    assert "[missing] tier 1 missing-cli" in output
    assert "No backend was called." in output


def test_doctor_json_is_machine_readable(tmp_path, capsys):
    target = tmp_path / "tierlane.toml"
    assert main(["init", "--output", str(target)]) == 0
    capsys.readouterr()

    assert main(["doctor", "--config", str(target), "--json"]) == 0

    import json

    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "doctor"
    assert report["called_backends"] is False
    assert len(report["tiers"]) == 4

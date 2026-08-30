"""CLI setup behavior that must work after an installed-package launch."""

from __future__ import annotations

import pytest

from tierlane.cli import main
from tierlane.config import load_config
from tierlane import __version__


def test_package_version_matches_release():
    assert __version__ == "0.2.0"


def test_version_flag_reports_the_release(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "tierlane 0.2.0"


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

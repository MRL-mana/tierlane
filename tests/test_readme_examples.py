"""Verify documented routing without invoking an AI backend."""

from importlib import resources
from pathlib import Path
import re

import pytest

from tierlane.config import load_config
from tierlane.router import pick_tier, should_hold


@pytest.mark.parametrize(
    ("task", "expected_tier", "held"),
    [
        ("translate this changelog to Japanese", 0, False),
        ("review the error handling in this module", 2, False),
        ("このモジュールのエラー処理をレビューして", 0, False),
        ("このファイルの変更点を要約して", 0, False),
        ("本番へ公開して", 0, False),
        ("deploy to production", 0, True),
    ],
)
def test_documented_default_routing(tmp_path, task, expected_tier, held):
    target = tmp_path / "tierlane.toml"
    target.write_text(
        resources.files("tierlane").joinpath("default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_config(target)
    assert pick_tier(task, config) == expected_tier
    assert should_hold(task, config) is held


def test_japanese_readme_config_routes_and_holds(tmp_path):
    readme = Path(__file__).resolve().parents[1] / "README.ja.md"
    snippets = re.findall(r"```toml\n(.*?)\n```", readme.read_text(encoding="utf-8"), re.DOTALL)
    assert len(snippets) == 1
    target = tmp_path / "tierlane.toml"
    target.write_text(snippets[0], encoding="utf-8")
    config = load_config(target)
    assert pick_tier("翻訳して", config) == 0
    assert pick_tier("このモジュールのエラー処理をレビューして", config) == 2
    assert pick_tier("翻訳してから設計をレビューして", config) == 2
    assert config.tier(2).cloud is True
    assert should_hold("本番へ公開して", config) is True
    assert should_hold("このファイルを削除して", config) is True
    assert should_hold("deploy to production", config) is True

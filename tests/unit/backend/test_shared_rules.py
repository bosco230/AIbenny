"""Shared companion rules (config/shared_rules.yml) reach every character."""

from __future__ import annotations

from pathlib import Path

from openmimicry_backend.routes.chat import load_shared_rules


def test_repo_shared_rules_contain_bible_section() -> None:
    rules = load_shared_rules()
    assert rules is not None
    assert "聖經" in rules and "逐字" in rules


def test_shared_rules_join_sections_and_tolerate_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "shared_rules.yml"
    path.write_text("bible: |\n  規則一\nother: |\n  規則二\n", encoding="utf-8")
    assert load_shared_rules(path) == "規則一\n\n規則二"
    assert load_shared_rules(tmp_path / "missing.yml") is None

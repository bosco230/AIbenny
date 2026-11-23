"""Buddhist scripture retrieval shared by Benny and 叮當."""

from __future__ import annotations

from pathlib import Path

import pytest

from openmimicry_backend.buddhist_search import build_context, find_passages
from openmimicry_backend.routes.chat import load_shared_rules

DB = Path(__file__).resolve().parents[3] / "data" / "buddhist" / "buddhist.sqlite"
pytestmark = pytest.mark.skipif(
    not DB.is_file(), reason="run scripts/build_buddhist_db.py to create the local database"
)


@pytest.mark.parametrize(
    ("question", "sutra", "needle"),
    [
        ("色即是空係咩意思？", "般若波羅蜜多心經", "色即是空"),
        ("應無所住而生其心點解？", "金剛般若波羅蜜經", "應無所住而生其心"),
        ("金剛經最出名係邊句？", "金剛般若波羅蜜經", "一切有為法"),
        ("佛家點睇無常？", "金剛般若波羅蜜經", "如夢、幻、泡、影"),
        ("我屋企人過身，佛教點睇往生？", "佛說阿彌陀經", "執持名號"),
        ("觀音菩薩點樣救苦？", "妙法蓮華經觀世音菩薩普門品", "一心稱名"),
    ],
)
def test_questions_find_original_passages(question: str, sutra: str, needle: str) -> None:
    passages = find_passages(DB, question)
    assert passages, question
    assert any(p.sutra == sutra and needle in p.text for p in passages)


def test_heart_sutra_is_returned_whole() -> None:
    passages = find_passages(DB, "幫我讀心經")
    joined = "".join(p.text for p in passages)
    assert joined.startswith("觀自在菩薩") and "菩提莎婆訶" in joined


@pytest.mark.parametrize(
    "question",
    ["你今日好嗎？", "我鍾意飲凍奶茶，少甜", "真係不可思議", "我一心一意想你", "約翰福音3:16講咩？"],
)
def test_everyday_chat_and_bible_questions_do_not_pull_sutras(question: str) -> None:
    assert find_passages(DB, question) == []


def test_context_is_bounded_and_keeps_original_text() -> None:
    context = build_context(find_passages(DB, "幫我讀心經"))
    assert context is not None and "逐字保留" in context
    assert len(context) < 1300


def test_shared_rules_include_buddhism_for_both_characters() -> None:
    rules = load_shared_rules()
    assert rules is not None and "佛經" in rules and "聖經" in rules

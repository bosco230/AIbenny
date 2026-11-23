"""Phase 2 memory: semantic recall, summaries, event follow-ups, date parsing."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from openmimicry.memory import LocalSQLiteMemory, MemoryService  # noqa: E402
from openmimicry.memory.extractors import LLMExtractor, resolve_spoken_date  # noqa: E402
from openmimicry.memory.models import MemoryCandidate  # noqa: E402
from openmimicry.memory.semantic import (  # noqa: E402
    SemanticStore,
    is_noise_predicate,
    parse_event,
)

MONDAY = date(2026, 11, 23)


class _KeywordEmbedder:
    """Deterministic fake: one dimension per keyword."""

    model = "fake"
    keywords = ("奶茶", "飲", "貓", "面試", "老細", "六合彩")

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        vectors = []
        for text in texts:
            vector = [1.0 if word in text else 0.0 for word in self.keywords]
            vector.append(0.1)  # never all-zero
            vectors.append(vector)
        return vectors

    async def close(self) -> None:
        return None


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我下星期三要去見工", date(2026, 12, 2)),
        ("今個星期五去旅行", date(2026, 11, 27)),
        ("聽日要睇牙醫", date(2026, 11, 24)),
        ("後日返鄉下", date(2026, 11, 25)),
        ("星期日去行山", date(2026, 11, 29)),
        ("今日好攰", MONDAY),
        ("我養咗隻貓", None),
        ("聽日同下星期三都要開會", None),
    ],
)
def test_resolve_spoken_date(text: str, expected: date | None) -> None:
    assert resolve_spoken_date(text, MONDAY) == expected


def test_noise_predicates_and_event_parsing() -> None:
    assert is_noise_predicate("user_emotion")
    assert is_noise_predicate("user_request_language")
    assert not is_noise_predicate("likes")
    assert not is_noise_predicate("user_intent")
    assert parse_event("2026-12-02 面試") == (date(2026, 12, 2), "面試")
    assert parse_event("面試") is None


def test_extractor_corrects_llm_event_date(monkeypatch: pytest.MonkeyPatch) -> None:
    import openmimicry.memory.extractors as extractors

    class _Today(date):
        @classmethod
        def today(cls):  # type: ignore[override]
            return MONDAY

    monkeypatch.setattr(extractors, "date", _Today)
    llm = _FakeLLM(
        '<think>x</think>{"memories":[{"predicate":"event","value":"2026-12-01 面試","confidence":0.9},'
        '{"predicate":"user_emotion","value":"緊張","confidence":0.9}]}'
    )
    found = asyncio.run(LLMExtractor(llm).extract("我下星期三要去見工，好緊張呀?", ""))
    assert [(c.predicate, c.value) for c in found] == [("event", "2026-12-02 面試")]
    assert "2026-12-02=星期三" in llm.prompts[0]


def test_pure_question_creates_no_memory() -> None:
    llm = _FakeLLM('{"memories":[{"predicate":"likes","value":"奶茶","confidence":1}]}')
    assert asyncio.run(LLMExtractor(llm).extract("你記唔記得我鍾意飲咩?", "")) == []


def _service(tmp_path: Path, summary_llm=None) -> tuple[MemoryService, LocalSQLiteMemory]:  # type: ignore[no-untyped-def]
    db = tmp_path / "memory.sqlite3"
    provider = LocalSQLiteMemory(db)
    service = MemoryService(
        provider=provider,
        retrieval_deadline_ms=2000,
        semantic=SemanticStore(db, _KeywordEmbedder()),  # type: ignore[arg-type]
        semantic_deadline_ms=2000,
        semantic_threshold=0.5,
        summary_llm=summary_llm,
    )
    return service, provider


def test_semantic_context_includes_core_relevant_and_events(tmp_path: Path) -> None:
    async def scenario() -> str | None:
        service, provider = _service(tmp_path)
        soon = (date.today() + timedelta(days=2)).isoformat()
        await provider.retain(
            [
                MemoryCandidate(predicate="name", value="阿明"),
                MemoryCandidate(predicate="likes", value="凍奶茶"),
                MemoryCandidate(predicate="pet", value="貓：咪咪"),
                MemoryCandidate(predicate="fact", value="中過六合彩"),
                MemoryCandidate(predicate="event", value=f"{soon} 面試"),
                MemoryCandidate(predicate="user_emotion", value="angry"),
            ],
            source="test",
        )
        context = await service.context("我鍾意飲咩奶茶？")
        await service.close()
        return context

    context = asyncio.run(scenario())
    assert context is not None
    assert "name: 阿明" in context  # core facts always present
    assert "鍾意：凍奶茶" in context  # semantic match
    assert "六合彩" not in context  # unrelated fact filtered by margin
    assert "angry" not in context  # noise never recalled
    assert "面試" in context and "2日後" in context


def test_summaries_and_followups(tmp_path: Path) -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        llm = _FakeLLM("使用者俾老細誤會咗，打算聽日解釋。")
        service, provider = _service(tmp_path, summary_llm=llm)
        summary = await service.summarize([("老細鬧我", "咩事呀？")])
        listed = await service.summaries()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        await provider.retain(
            [MemoryCandidate(predicate="event", value=f"{yesterday} 面試")], source="test"
        )
        due = await service.due_followup()
        assert due is not None
        await service.mark_followed_up(due.memory_id)
        after = await service.due_followup()
        context = await service.context("老細嗰單嘢點呀")
        empty = await _FakeNone(service)
        await service.close()
        return summary, listed, due, after, context, empty

    summary, listed, due, after, context, empty = asyncio.run(scenario())
    assert summary is not None and listed[0].text == summary.text
    assert due.description == "面試"
    assert after is None
    assert "之前對話嘅摘要" in context and "誤會" in context
    assert empty is None


async def _FakeNone(service: MemoryService):  # type: ignore[no-untyped-def]
    service._summary_llm = _FakeLLM("NONE")  # noqa: SLF001
    return await service.summarize([("你好", "你好呀")])

"""One chat turn for one visitor: persona + rules + knowledge + memory -> reply.

Reuses the desktop modules read-only:
  openmimicry_backend.llm_response  persona loading / JSON reply parsing
  openmimicry_backend.bible_search, bible_topics, buddhist_search, novels
  openmimicry.memory               long-term memory (one SQLite file per visitor)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openmimicry.memory import LocalSQLiteMemory, MemoryService
from openmimicry.memory.extractors import LLMExtractor
from openmimicry.memory.semantic import OllamaEmbedder, SemanticStore
from openmimicry_backend.bible_search import find_reference
from openmimicry_backend.bible_topics import retrieve_topic
from openmimicry_backend.buddhist_search import build_context as buddhist_context
from openmimicry_backend.buddhist_search import find_passages as buddhist_passages
from openmimicry_backend.llm_response import load_personality, parse_assistant_reply
from openmimicry_backend.novels import Book, NovelLibrary

from .llm import HelperCompletion, OpenRouter
from .settings import Settings

_log = logging.getLogger(__name__)
SUMMARY_BATCH = 8
MAX_VISITORS_IN_MEMORY = 200


def load_shared_rules(path: Path) -> str:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    return "\n\n".join(str(v).strip() for v in data.values() if isinstance(v, str) and v.strip())


def bible_context(database: Path, text: str) -> str | None:
    """Same retrieval and wording as the desktop chat route."""

    if not database.is_file():
        return None
    verse = find_reference(database, text)
    if verse is not None:
        reference = f'{verse["book_name"]} {verse["chapter"]}:{verse["verse"]}'
        return (
            "以下係本地繁體中文和合本聖經參考資料。引用經文時，必須逐字保留資料庫原文，"
            "包括用字、標點及方括號，不得改寫或翻譯。請清楚標示經文出處，並區分原文與解釋。"
            "經文以外的解釋請使用自然廣東話。保留原有角色個性及回覆格式。"
            f"\n經文出處：{reference}\n經文內容：{verse['text']}"
        )
    topic = retrieve_topic(database, text)
    if topic is None:
        return None
    lines = [
        f'{v["book_name"]} {v["chapter"]}:{v["verse"]}\n{v["text"]}' for v in topic["verses"]
    ]
    return (
        "以下係本地繁體中文和合本聖經主題參考資料。主題：" + topic["topic"]
        + "\n引用經文時必須逐字保留資料庫原文，包括用字、標點及方括號，不得改寫或翻譯。"
        "請清楚標示經文出處，並區分原文與解釋。經文以外請使用自然廣東話解釋。"
        "保留原有角色個性及回覆格式。\n\n" + "\n\n".join(lines)
    )


class VisitorNovels(NovelLibrary):
    """Shared book index, but reading progress kept per visitor.

    The desktop library stores progress in its database; on the web every
    visitor needs their own, so progress lives in a small JSON file instead.
    """

    def __init__(self, shared: NovelLibrary, progress_path: Path) -> None:
        self.__dict__.update(shared.__dict__)  # share index, embedder, terms
        self._shared = shared
        self._progress_path = progress_path

    def _progress(self) -> dict[str, int]:
        try:
            return {k: int(v) for k, v in json.loads(self._progress_path.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError):
            return {}

    async def books(self) -> list[Book]:
        books = await self._shared.books()
        progress = self._progress()
        result = []
        for book in books:
            chapter = progress.get(str(book.id))
            title = None
            if chapter:
                title = await asyncio.to_thread(self._run, _chapter_title, book.id, chapter)
            result.append(Book(**{**book.__dict__, "progress": chapter, "progress_title": title}))
        return result

    async def set_progress(self, book_id: int, chapter: int | None) -> None:
        progress = self._progress()
        if chapter is None:
            progress.pop(str(book_id), None)
        else:
            progress[str(book_id)] = int(chapter)
        self._progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._progress_path.write_text(json.dumps(progress), encoding="utf-8")

    async def _load_index(self) -> None:
        await self._shared._load_index()
        self._matrix, self._meta = self._shared._matrix, self._shared._meta


def _chapter_title(c: Any, book_id: int, number: int) -> str | None:
    row = c.execute("SELECT title FROM chapters WHERE book_id = ? AND number = ?", (book_id, number)).fetchone()
    return row["title"] if row else None


@dataclass
class Visitor:
    memory: MemoryService
    novels: VisitorNovels
    history: dict[str, deque[tuple[str, str]]] = field(default_factory=dict)
    pending_summary: list[tuple[str, str]] = field(default_factory=list)


class Brain:
    def __init__(self, settings: Settings, llm: OpenRouter, embedder: Any | None = None) -> None:
        self.settings = settings
        self.llm = llm
        data = settings.data_dir
        self._embedder = embedder if embedder is not None else OllamaEmbedder(
            model=settings.embedding_model, base_url=settings.ollama_url
        )
        self.novels = NovelLibrary(
            data / "novels.sqlite", data / "novels_inbox", self._embedder,
            terms_path=settings.config_dir / "novel_terms.yml",
        )
        self._visitors: OrderedDict[str, Visitor] = OrderedDict()
        self._tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------ visitors

    def visitor(self, visitor_id: str) -> Visitor:
        if visitor_id in self._visitors:
            self._visitors.move_to_end(visitor_id)
            return self._visitors[visitor_id]
        folder = self.settings.data_dir / "visitors"
        db = folder / f"{visitor_id}.sqlite"
        extractor_llm = HelperCompletion(self.llm, self.settings.helper_model,
                                         "You extract durable user memories into strict JSON.")
        summary_llm = HelperCompletion(self.llm, self.settings.helper_model,
                                       "你負責將對話寫成簡短、客觀嘅繁體中文摘要。")
        memory = MemoryService(
            provider=LocalSQLiteMemory(db, retention_days=365),
            retrieval_limit=6,
            retrieval_deadline_ms=400,
            extraction="llm",
            llm_extractor=LLMExtractor(extractor_llm),
            bilingual_extraction=True,
            reconcile_preferences=True,
            merge_llm_bilingual=True,
            semantic=SemanticStore(db, self._embedder),
            semantic_deadline_ms=1500,
            summary_llm=summary_llm,
        )
        visitor = Visitor(memory=memory, novels=VisitorNovels(self.novels, folder / f"{visitor_id}.progress.json"))
        self._visitors[visitor_id] = visitor
        while len(self._visitors) > MAX_VISITORS_IN_MEMORY:
            self._visitors.popitem(last=False)
        return visitor

    def _background(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --------------------------------------------------------------- turn

    async def reply(self, visitor_id: str, character_id: str, text: str) -> dict[str, Any]:
        character = self.settings.characters[character_id]
        persona = load_personality(character.persona)
        visitor = self.visitor(visitor_id)
        history = visitor.history.setdefault(character_id, deque(maxlen=self.settings.history_turns))

        knowledge: list[str] = []
        try:
            async with asyncio.timeout(3.0):
                memory = await visitor.memory.context(text)
            if memory:
                knowledge.append(memory)
        except Exception:
            _log.warning("memory context failed", exc_info=True)
        try:
            async with asyncio.timeout(3.0):
                novel = await visitor.novels.context(text)
            if novel:
                knowledge.append(novel)
        except Exception:
            _log.warning("novel context failed", exc_info=True)
        for builder in (
            lambda: bible_context(self.settings.data_dir / "bible.sqlite", text),
            lambda: buddhist_context(buddhist_passages(self.settings.data_dir / "buddhist.sqlite", text)),
        ):
            try:
                extra = builder()
                if extra:
                    knowledge.append(extra)
            except Exception:
                _log.warning("scripture context failed", exc_info=True)

        messages = [{"role": "system", "content": persona.system_prompt}]
        rules = load_shared_rules(self.settings.config_dir / "shared_rules.yml")
        if rules:
            messages.append({"role": "system", "content": rules})
        for user, assistant in history:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": assistant})
        messages.extend({"role": "system", "content": item} for item in knowledge)
        messages.append({"role": "user", "content": text})

        raw = await self.llm.chat(messages, model=self.settings.chat_model, json_mode=True)
        parsed = parse_assistant_reply(raw, persona)
        reply = parsed.text.strip() or "唔好意思，我諗唔到點答，可唔可以講多次？"
        history.append((text, reply))

        visitor.memory.observe(text, reply, source=f"web:{character_id}")
        visitor.pending_summary.append((text, reply))
        if len(visitor.pending_summary) >= SUMMARY_BATCH:
            batch, visitor.pending_summary = visitor.pending_summary, []
            self._background(visitor.memory.summarize(batch))

        return {
            "character": character_id,
            "reply": reply,
            "emotion": parsed.emotion,
            "intensity": parsed.intensity,
        }

    async def forget(self, visitor_id: str) -> None:
        visitor = self.visitor(visitor_id)
        await visitor.memory.clear()
        visitor.history.clear()
        visitor.pending_summary.clear()
        visitor.novels._progress_path.unlink(missing_ok=True)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for visitor in self._visitors.values():
            await visitor.memory.close()
        self._visitors.clear()

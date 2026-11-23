"""Semantic recall, conversation summaries and event follow-ups for Benny.

Everything lives beside the ``memories`` table in the same local SQLite file:

* ``memory_vectors`` — one embedding per memory row, built lazily.
* ``conversation_summaries`` — short LLM summaries of finished stretches of
  conversation, each with its own embedding.
* ``event_followups`` — which dated events Benny has already asked about.

Embeddings come from a local Ollama model (``bge-m3`` by default). With a few
thousand rows a brute-force numpy cosine scan takes well under a millisecond,
so no vector extension is needed. Every embedding call is optional: when
Ollama is unreachable recall silently falls back to the lexical path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sqlite3
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "CORE_PREDICATES",
    "DueEvent",
    "OllamaEmbedder",
    "SemanticStore",
    "Summary",
    "is_noise_predicate",
    "parse_event",
]

_log = logging.getLogger(__name__)

# Facts about who the user is. They are injected on every turn, whatever the
# question, so Benny never "forgets" the user's name or job.
CORE_PREDICATES = frozenset(
    {
        "name",
        "user_name",
        "nickname",
        "中文名",
        "花名",
        "job",
        "workplace",
        "work_history",
        "上司",
        "family",
        "partner",
        "pet",
        "user_pet_relationship",
        "location",
        "birthday",
        "language_preference",
    }
)

# Transient states and meta-requests the old extractor stored. They are kept
# in the database (the user can review them) but never recalled as facts.
_NOISE_PREFIXES = (
    "user_emotion",
    "user_mood",
    "user_feeling",
    "user_expression",
    "user_last_message",
    "user_request",
    "user_greeting",
    "user_speaks",
    "user_language",
    "user_eaten",
    "topic_of_conversation",
    "language_used",
    "weather",
    "activity",
)

_EVENT_PATTERN = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*[:：\-\s]\s*(.+)$")


def is_noise_predicate(predicate: str) -> bool:
    key = predicate.strip().casefold()
    return any(key.startswith(prefix) for prefix in _NOISE_PREFIXES)


def parse_event(value: str) -> tuple[date, str] | None:
    """Split an ``event`` value stored as ``YYYY-MM-DD 描述``."""

    match = _EVENT_PATTERN.match(value)
    if not match:
        return None
    try:
        when = date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return when, match.group(2).strip()


class OllamaEmbedder:
    """Minimal async client for Ollama's ``/api/embed`` endpoint."""

    def __init__(
        self,
        *,
        model: str = "bge-m3",
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: float = 60.0,
        keep_alive: str = "30m",
    ) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + "/api/embed"
        self._timeout_s = timeout_s
        self._keep_alive = keep_alive
        self._client: Any = None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        response = await self._client.post(
            self._url,
            json={"model": self.model, "input": list(texts), "keep_alive": self._keep_alive},
        )
        response.raise_for_status()
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama returned an unexpected embedding payload")
        return vectors

    async def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None


@dataclass(frozen=True)
class Summary:
    id: str
    text: str
    created_at: datetime


@dataclass(frozen=True)
class DueEvent:
    memory_id: str
    when: date
    description: str


class SemanticStore:
    """Vectors, summaries and follow-up bookkeeping in the memory database."""

    def __init__(self, path: str | Path, embedder: OllamaEmbedder | None) -> None:
        self._path = Path(path).expanduser()
        self._embedder = embedder
        self._lock = asyncio.Lock()
        self._initialized = False
        # memory_id -> (vector, text) for rows already embedded.
        self._cache: dict[str, Any] = {}
        self._summary_cache: dict[str, Any] = {}

    @property
    def embedder(self) -> OllamaEmbedder | None:
        return self._embedder

    # ------------------------------------------------------------- storage

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _run(self, fn, *args):  # type: ignore[no-untyped-def]
        connection = self._connect()
        try:
            with connection:
                return fn(connection, *args)
        finally:
            connection.close()

    async def _ensure_ready(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._run, _create_tables)
            self._initialized = True

    # -------------------------------------------------------------- vectors

    async def sync(self, rows: Iterable[Any], *, max_new: int = 64) -> int:
        """Embed memory rows that have no vector yet; drop vectors of deleted rows."""

        await self._ensure_ready()
        if self._embedder is None:
            return 0
        rows = list(rows)
        if not self._cache:
            stored = await asyncio.to_thread(self._run, _load_vectors, self._embedder.model)
            self._cache.update(stored)
        live = {row.id: _memory_text(row.predicate, row.value) for row in rows}
        stale = [
            memory_id
            for memory_id, (_, text) in self._cache.items()
            if live.get(memory_id) != text
        ]
        if stale:
            for memory_id in stale:
                self._cache.pop(memory_id, None)
            await asyncio.to_thread(self._run, _delete_vectors, stale)
        missing = [(mid, text) for mid, text in live.items() if mid not in self._cache][:max_new]
        if not missing:
            return 0
        import numpy as np

        stored = 0
        # Small batches keep each request well inside the HTTP timeout, even
        # while Ollama is still loading the embedding model.
        for start in range(0, len(missing), 16):
            batch = missing[start : start + 16]
            vectors = await self._embedder.embed([text for _, text in batch])
            payload = []
            for (memory_id, text), vector in zip(batch, vectors, strict=True):
                array = _normalise(np.asarray(vector, dtype=np.float32))
                self._cache[memory_id] = (array, text)
                payload.append((memory_id, self._embedder.model, text, array.tobytes()))
            await asyncio.to_thread(self._run, _store_vectors, payload)
            stored += len(payload)
        return stored

    async def embed_query(self, text: str) -> Any | None:
        if self._embedder is None:
            return None
        import numpy as np

        vectors = await self._embedder.embed([text])
        return _normalise(np.asarray(vectors[0], dtype=np.float32))

    def rank(
        self,
        query_vector: Any,
        *,
        limit: int,
        threshold: float,
        margin: float = 0.06,
    ) -> list[tuple[str, float]]:
        """Top matches above ``threshold`` and within ``margin`` of the best.

        bge-m3 cosine scores for short Chinese facts bunch up between 0.4 and
        0.7, so an absolute cut-off alone lets unrelated facts through. Keeping
        only hits close to the best one separates "奶茶" from "漢堡包" when the
        question is about drinks.
        """

        if query_vector is None or not self._cache:
            return []
        scored = [
            (memory_id, float(vector @ query_vector))
            for memory_id, (vector, _) in self._cache.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        if not scored or scored[0][1] < threshold:
            return []
        floor = max(threshold, scored[0][1] - margin)
        return [(mid, score) for mid, score in scored[:limit] if score >= floor]

    # ------------------------------------------------------------ summaries

    async def add_summary(self, text: str) -> Summary:
        await self._ensure_ready()
        summary = Summary(id=uuid.uuid4().hex, text=text.strip(), created_at=_utc_now())
        vector_bytes = None
        model = None
        if self._embedder is not None:
            with contextlib.suppress(Exception):
                vector = await self.embed_query(summary.text)
                if vector is not None:
                    self._summary_cache[summary.id] = vector
                    vector_bytes = vector.tobytes()
                    model = self._embedder.model
        await asyncio.to_thread(self._run, _store_summary, summary, model, vector_bytes)
        return summary

    async def summaries(self, *, limit: int = 50) -> list[Summary]:
        await self._ensure_ready()
        rows = await asyncio.to_thread(self._run, _list_summaries, limit)
        return [
            Summary(id=row["id"], text=row["text"], created_at=_parse_ts(row["created_at"]))
            for row in rows
        ]

    async def delete_summary(self, summary_id: str) -> bool:
        await self._ensure_ready()
        self._summary_cache.pop(summary_id, None)
        return bool(await asyncio.to_thread(self._run, _delete_summary, summary_id))

    async def clear_summaries(self) -> int:
        await self._ensure_ready()
        self._summary_cache.clear()
        return int(await asyncio.to_thread(self._run, _clear_summaries))

    async def relevant_summaries(
        self, query_vector: Any | None, *, limit: int = 2, threshold: float = 0.5
    ) -> list[Summary]:
        """Most recent summary plus the best semantic matches."""

        recent = await self.summaries(limit=200)
        if not recent:
            return []
        chosen: list[Summary] = [recent[0]]
        if query_vector is not None and self._embedder is not None:
            if len(self._summary_cache) < len(recent):
                stored = await asyncio.to_thread(
                    self._run, _load_summary_vectors, self._embedder.model
                )
                self._summary_cache.update(stored)
            by_id = {item.id: item for item in recent}
            scored = sorted(
                (
                    (float(vector @ query_vector), summary_id)
                    for summary_id, vector in self._summary_cache.items()
                    if summary_id in by_id
                ),
                reverse=True,
            )
            for score, summary_id in scored:
                if len(chosen) >= limit or score < threshold:
                    break
                if summary_id != chosen[0].id:
                    chosen.append(by_id[summary_id])
        return chosen

    # -------------------------------------------------------------- events

    async def due_followup(
        self, rows: Iterable[Any], *, today: date | None = None, lookback_days: int = 3
    ) -> DueEvent | None:
        """Oldest event that happened in the last few days and was not followed up."""

        await self._ensure_ready()
        today = today or date.today()
        done = set(await asyncio.to_thread(self._run, _followed_ids))
        candidates: list[DueEvent] = []
        for row in rows:
            if str(row.predicate).casefold() != "event" or row.id in done:
                continue
            parsed = parse_event(str(row.value))
            if parsed is None:
                continue
            when, description = parsed
            if today - timedelta(days=lookback_days) <= when <= today:
                candidates.append(DueEvent(row.id, when, description))
        candidates.sort(key=lambda item: item.when)
        return candidates[0] if candidates else None

    async def mark_followed_up(self, memory_id: str) -> None:
        await self._ensure_ready()
        await asyncio.to_thread(self._run, _mark_followed, memory_id)

    async def close(self) -> None:
        if self._embedder is not None:
            await self._embedder.close()


# ------------------------------------------------------------------ helpers


def upcoming_events(
    rows: Iterable[Any], *, today: date | None = None, ahead_days: int = 14, behind_days: int = 3
) -> list[tuple[date, str]]:
    today = today or date.today()
    found: list[tuple[date, str]] = []
    for row in rows:
        if str(row.predicate).casefold() != "event":
            continue
        parsed = parse_event(str(row.value))
        if parsed is None:
            continue
        when, description = parsed
        if today - timedelta(days=behind_days) <= when <= today + timedelta(days=ahead_days):
            found.append((when, description))
    found.sort()
    return found


def _memory_text(predicate: str, value: str) -> str:
    return f"{predicate}: {value}"


def _normalise(vector: Any) -> Any:
    import numpy as np

    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return _utc_now()


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS memory_vectors (
        memory_id TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        text TEXT NOT NULL,
        vector BLOB NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS conversation_summaries (
        id TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        model TEXT,
        vector BLOB
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS event_followups (
        memory_id TEXT PRIMARY KEY,
        followed_at TEXT NOT NULL
        )"""
    )


def _load_vectors(connection: sqlite3.Connection, model: str) -> dict[str, Any]:
    import numpy as np

    result: dict[str, Any] = {}
    for row in connection.execute(
        "SELECT memory_id, text, vector FROM memory_vectors WHERE model = ?", (model,)
    ):
        result[row["memory_id"]] = (np.frombuffer(row["vector"], dtype=np.float32), row["text"])
    return result


def _store_vectors(connection: sqlite3.Connection, payload: list[tuple[str, str, str, bytes]]) -> None:
    connection.executemany(
        "INSERT OR REPLACE INTO memory_vectors(memory_id, model, text, vector) VALUES (?, ?, ?, ?)",
        payload,
    )


def _delete_vectors(connection: sqlite3.Connection, ids: list[str]) -> None:
    connection.executemany("DELETE FROM memory_vectors WHERE memory_id = ?", [(i,) for i in ids])


def _store_summary(
    connection: sqlite3.Connection, summary: Summary, model: str | None, vector: bytes | None
) -> None:
    connection.execute(
        "INSERT INTO conversation_summaries(id, text, created_at, model, vector) VALUES (?, ?, ?, ?, ?)",
        (summary.id, summary.text, summary.created_at.isoformat(), model, vector),
    )


def _list_summaries(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            "SELECT id, text, created_at FROM conversation_summaries ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )


def _load_summary_vectors(connection: sqlite3.Connection, model: str) -> dict[str, Any]:
    import numpy as np

    return {
        row["id"]: np.frombuffer(row["vector"], dtype=np.float32)
        for row in connection.execute(
            "SELECT id, vector FROM conversation_summaries WHERE model = ? AND vector IS NOT NULL",
            (model,),
        )
    }


def _delete_summary(connection: sqlite3.Connection, summary_id: str) -> int:
    return connection.execute(
        "DELETE FROM conversation_summaries WHERE id = ?", (summary_id,)
    ).rowcount


def _clear_summaries(connection: sqlite3.Connection) -> int:
    return connection.execute("DELETE FROM conversation_summaries").rowcount


def _followed_ids(connection: sqlite3.Connection) -> list[str]:
    return [row["memory_id"] for row in connection.execute("SELECT memory_id FROM event_followups")]


def _mark_followed(connection: sqlite3.Connection, memory_id: str) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO event_followups(memory_id, followed_at) VALUES (?, ?)",
        (memory_id, _utc_now().isoformat()),
    )

"""Null, local SQLite, and optional Hindsight provider adapters."""

from __future__ import annotations
from contextlib import contextmanager

import asyncio
import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .models import MemoryCandidate, MemoryRecord

__all__ = ["HindsightMemory", "LocalSQLiteMemory", "MemoryProvider", "NullMemory"]


class MemoryProvider(Protocol):
    async def recall(self, query: str, *, limit: int) -> list[MemoryRecord]: ...
    async def retain(self, candidates: Sequence[MemoryCandidate], *, source: str) -> None: ...
    async def list(self, *, limit: int = 100) -> list[MemoryRecord]: ...
    async def update(self, memory_id: str, candidate: MemoryCandidate) -> bool: ...
    async def delete(self, memory_id: str) -> bool: ...
    async def clear(self) -> int: ...
    async def close(self) -> None: ...


class NullMemory:
    async def recall(self, query: str, *, limit: int) -> list[MemoryRecord]:
        return []

    async def retain(self, candidates: Sequence[MemoryCandidate], *, source: str) -> None:
        return None

    async def list(self, *, limit: int = 100) -> list[MemoryRecord]:
        return []

    async def delete(self, memory_id: str) -> bool:
        return False

    async def update(self, memory_id: str, candidate: MemoryCandidate) -> bool:
        return False

    async def clear(self) -> int:
        return 0

    async def close(self) -> None:
        return None


class LocalSQLiteMemory:
    """Small local store with exact-fact dedupe and lexical retrieval."""

    def __init__(self, path: str | Path, *, retention_days: int | None = 365) -> None:
        self._path = Path(path).expanduser()
        self._retention_days = retention_days
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_ready(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if not self._initialized:
                await asyncio.to_thread(self._initialize_sync)
                self._initialized = True


    # BENNY_SQLITE_CONNECTION_LIFECYCLE_110E9I
    @contextmanager
    def _managed_connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_sync(self) -> None:
        with self._managed_connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(subject, predicate, normalized_value)
                )"""
            )


    async def retain_with_preference_reconciliation(
        self,
        candidates: Sequence[MemoryCandidate],
        *,
        source: str,
    ) -> None:
        if not candidates:
            return

        await self._ensure_ready()

        async with self._lock:
            await asyncio.to_thread(
                self._retain_with_preference_reconciliation_sync,
                list(candidates),
                source[:256],
            )

    def _retain_with_preference_reconciliation_sync(
        self,
        candidates: list[MemoryCandidate],
        source: str,
    ) -> None:
        with self._managed_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._purge_expired_sync(connection)

            for candidate in candidates:
                normalized = " ".join(
                    candidate.value.casefold().split()
                )

                predicate = candidate.predicate.strip().casefold()
                subject = candidate.subject.strip().casefold()

                if subject != "user" or predicate not in {
                    "likes", "dislikes"
                }:
                    self._insert_memory_candidate(
                        connection, candidate, source
                    )
                    continue

                rows = connection.execute(
                    """SELECT id, predicate
                    FROM memories
                    WHERE subject = ?
                      AND normalized_value = ?
                      AND predicate IN ('likes', 'dislikes', '喜好')""",
                    (candidate.subject, normalized),
                ).fetchall()

                if len(rows) > 1:
                    # Preserve ambiguous existing records.
                    continue

                if len(rows) == 1:
                    existing = rows[0]

                    if existing["predicate"] == "\u559c\u597d":
                        if predicate != "likes":
                            continue

                    if existing["predicate"] == candidate.predicate:
                        self._insert_memory_candidate(
                            connection, candidate, source
                        )
                        continue

                    now = datetime.now(timezone.utc).isoformat()

                    connection.execute(
                        """UPDATE memories
                        SET predicate = ?,
                            value = ?,
                            normalized_value = ?,
                            confidence = ?,
                            source = ?,
                            updated_at = ?
                        WHERE id = ?""",
                        (
                            candidate.predicate,
                            candidate.value,
                            normalized,
                            candidate.confidence,
                            source,
                            now,
                            existing["id"],
                        ),
                    )
                    continue

                self._insert_memory_candidate(
                    connection, candidate, source
                )

    def _insert_memory_candidate(
        self,
        connection: sqlite3.Connection,
        candidate: MemoryCandidate,
        source: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        normalized = " ".join(
            candidate.value.casefold().split()
        )

        connection.execute(
            """INSERT INTO memories
            (id, subject, predicate, value, normalized_value,
             confidence, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject, predicate, normalized_value)
            DO UPDATE SET
                confidence = MAX(confidence, excluded.confidence),
                source = excluded.source,
                updated_at = excluded.updated_at""",
            (
                uuid4().hex,
                candidate.subject,
                candidate.predicate,
                candidate.value,
                normalized,
                candidate.confidence,
                source,
                now,
                now,
            ),
        )

    async def retain(self, candidates: Sequence[MemoryCandidate], *, source: str) -> None:
        if not candidates:
            return
        await self._ensure_ready()
        async with self._lock:
            await asyncio.to_thread(self._retain_sync, list(candidates), source[:256])

    def _retain_sync(self, candidates: list[MemoryCandidate], source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._managed_connection() as connection:
            self._purge_expired_sync(connection)
            for candidate in candidates:
                normalized = " ".join(candidate.value.casefold().split())
                connection.execute(
                    """INSERT INTO memories
                    (id, subject, predicate, value, normalized_value, confidence, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subject, predicate, normalized_value) DO UPDATE SET
                    confidence = MAX(confidence, excluded.confidence),
                    source = excluded.source,
                    updated_at = excluded.updated_at""",
                    (
                        uuid4().hex,
                        candidate.subject,
                        candidate.predicate,
                        candidate.value,
                        normalized,
                        candidate.confidence,
                        source,
                        now,
                        now,
                    ),
                )

    async def recall(self, query: str, *, limit: int) -> list[MemoryRecord]:
        await self._ensure_ready()
        rows = await asyncio.to_thread(self._all_rows_sync, 1000)

        normalized_query = query.casefold().strip()
        if not normalized_query or limit <= 0:
            return []

        negative_phrases = (
            "\u5514\u937e\u610f",
            "\u4e0d\u559c\u6b61",
            "\u5514\u559c\u6b61",
            "\u4e0d\u611b",
            "\u5514\u611b",
        )
        positive_phrases = (
            "\u937e\u610f",
            "\u559c\u6b61",
            "\u559c\u6b22",
            "\u611b",
        )

        negative = any(
            phrase in normalized_query for phrase in negative_phrases
        )
        positive = (
            not negative
            and any(phrase in normalized_query for phrase in positive_phrases)
        )

        drink_phrases = (
            "\u98f2", "\u559d", "\u98f2\u54a9",
            "\u559d\u4ec0\u9ebc", "\u98f2\u4ec0\u9ebc",
        )
        drink_query = any(
            phrase in normalized_query for phrase in drink_phrases
        )

        aliases = {
            "\u5e78\u904b\u6578\u5b57": ("lucky_number",),
            "\u5e78\u8fd0\u6570\u5b57": ("lucky_number",),
            "\u6e2c\u8a66": ("test",),
            "\u6d4b\u8bd5": ("test",),
            "\u4f4f": ("location",),
            "\u5c45\u4f4f": ("location",),
        }

        tokens = set(re.findall(r"[a-z0-9_'-]+", normalized_query))

        for phrase, equivalents in aliases.items():
            if phrase in normalized_query:
                tokens.update(equivalents)

        if positive:
            tokens.add("likes")
        elif negative:
            tokens.add("dislikes")

        drink_values = (
            "\u5976\u8336",
            "\u5496\u5561",
            "\u8336",
            "\u6c34",
            "\u679c\u6c41",
            "\u6c7d\u6c34",
            "\u5564\u9152",
            "\u7d05\u9152",
            "\u725b\u5976",
            "\u8c46\u6f3f",
            "\u53ef\u6a02",
        )

        def score(row: sqlite3.Row) -> tuple[int, str]:
            predicate = str(row["predicate"]).casefold()
            value = str(row["value"]).casefold()
            haystack = predicate + " " + value

            if negative and predicate == "likes":
                return (0, row["updated_at"])
            if positive and predicate == "dislikes":
                return (0, row["updated_at"])

            points = sum(
                2 for token in tokens
                if token in haystack
            )

            if value and len(value) >= 2 and value in normalized_query:
                points += 10

            if positive and predicate in ("likes", "\u559c\u597d"):
                points += 6
            elif negative and predicate == "dislikes":
                points += 6

            if drink_query:
                is_drink = any(
                    drink == value or drink in value
                    for drink in drink_values
                )
                if is_drink:
                    points += 8
                elif predicate.startswith("favorite_sport"):
                    points = 0

            return (points, row["updated_at"])

        ranked = sorted(rows, key=score, reverse=True)
        selected = [
            row for row in ranked if score(row)[0] > 0
        ][:limit]
        return [_row_to_record(row) for row in selected]


    async def list(self, *, limit: int = 100) -> list[MemoryRecord]:
        await self._ensure_ready()
        rows = await asyncio.to_thread(self._all_rows_sync, max(0, min(limit, 1000)))
        return [_row_to_record(row) for row in rows]

    def _all_rows_sync(self, limit: int) -> list[sqlite3.Row]:
        with self._managed_connection() as connection:
            self._purge_expired_sync(connection)
            return list(
                connection.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            )

    async def delete(self, memory_id: str) -> bool:
        await self._ensure_ready()
        async with self._lock:
            return await asyncio.to_thread(self._delete_sync, memory_id)


    # BENNY_ATOMIC_MEMORY_CORRECTION_110E9Q2
    async def replace_if_matches(
        self,
        memory_id: str,
        expected: MemoryCandidate,
        replacement: MemoryCandidate,
    ) -> bool:
        """Replace only when the stored fact matches the expected fact."""
        if (
            expected.subject != replacement.subject
            or expected.predicate != replacement.predicate
        ):
            return False

        await self._ensure_ready()
        async with self._lock:
            return await asyncio.to_thread(
                self._replace_if_matches_sync,
                memory_id,
                expected,
                replacement,
            )

    def _replace_if_matches_sync(
        self,
        memory_id: str,
        expected: MemoryCandidate,
        replacement: MemoryCandidate,
    ) -> bool:
        normalized = " ".join(replacement.value.casefold().split())
        expected_normalized = " ".join(expected.value.casefold().split())
        now = datetime.now(timezone.utc).isoformat()

        with self._managed_connection() as connection:
            try:
                cursor = connection.execute(
                    """UPDATE memories
                    SET value = ?, normalized_value = ?,
                        confidence = ?, updated_at = ?
                    WHERE id = ?
                      AND subject = ?
                      AND predicate = ?
                      AND normalized_value = ?
                      AND value = ?""",
                    (
                        replacement.value,
                        normalized,
                        replacement.confidence,
                        now,
                        memory_id,
                        expected.subject,
                        expected.predicate,
                        expected_normalized,
                        expected.value,
                    ),
                )
            except sqlite3.IntegrityError:
                return False

            return cursor.rowcount == 1

    async def update_if_matches(
        self,
        memory_id: str,
        expected: MemoryCandidate,
        replacement: MemoryCandidate,
    ) -> bool:
        """Update only when the stored memory matches the expected content."""
        await self._ensure_ready()
        async with self._lock:
            return await asyncio.to_thread(
                self._update_if_matches_sync,
                memory_id,
                expected,
                replacement,
            )

    def _update_if_matches_sync(
        self,
        memory_id: str,
        expected: MemoryCandidate,
        replacement: MemoryCandidate,
    ) -> bool:
        expected_normalized = " ".join(
            expected.value.casefold().split()
        )
        replacement_normalized = " ".join(
            replacement.value.casefold().split()
        )
        now = datetime.now(timezone.utc).isoformat()

        with self._managed_connection() as connection:
            try:
                cursor = connection.execute(
                    """UPDATE memories
                    SET subject = ?,
                        predicate = ?,
                        value = ?,
                        normalized_value = ?,
                        confidence = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND subject = ?
                      AND predicate = ?
                      AND normalized_value = ?
                      AND value = ?""",
                    (
                        replacement.subject,
                        replacement.predicate,
                        replacement.value,
                        replacement_normalized,
                        replacement.confidence,
                        now,
                        memory_id,
                        expected.subject,
                        expected.predicate,
                        expected_normalized,
                        expected.value,
                    ),
                )
            except sqlite3.IntegrityError:
                return False

            return cursor.rowcount == 1

    async def update(self, memory_id: str, candidate: MemoryCandidate) -> bool:
        await self._ensure_ready()
        async with self._lock:
            return await asyncio.to_thread(self._update_sync, memory_id, candidate)

    def _update_sync(self, memory_id: str, candidate: MemoryCandidate) -> bool:
        normalized = " ".join(candidate.value.casefold().split())
        now = datetime.now(timezone.utc).isoformat()
        with self._managed_connection() as connection:
            self._purge_expired_sync(connection)
            try:
                cursor = connection.execute(
                    """UPDATE memories SET subject = ?, predicate = ?, value = ?,
                    normalized_value = ?, confidence = ?, updated_at = ? WHERE id = ?""",
                    (
                        candidate.subject,
                        candidate.predicate,
                        candidate.value,
                        normalized,
                        candidate.confidence,
                        now,
                        memory_id,
                    ),
                )
            except sqlite3.IntegrityError:
                return False
            return cursor.rowcount > 0

    def _delete_sync(self, memory_id: str) -> bool:
        with self._managed_connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0

    async def clear(self) -> int:
        await self._ensure_ready()
        async with self._lock:
            return await asyncio.to_thread(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._managed_connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            connection.execute("DELETE FROM memories")
            return count

    def _purge_expired_sync(self, connection: sqlite3.Connection) -> int:
        if self._retention_days is None:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
        cursor = connection.execute("DELETE FROM memories WHERE updated_at < ?", (cutoff,))
        return cursor.rowcount

    async def close(self) -> None:
        return None


class HindsightMemory:
    """Thin optional wrapper around the official Hindsight Python client."""

    def __init__(self, *, base_url: str, bank_id: str = "openmimicry") -> None:
        try:
            from hindsight_client import Hindsight  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise RuntimeError(
                "Hindsight is not installed. Install openmimicry-memory[hindsight]."
            ) from exc
        self._client: Any = Hindsight(base_url=base_url)
        self._bank_id = bank_id

    async def retain(self, candidates: Sequence[MemoryCandidate], *, source: str) -> None:
        for candidate in candidates:
            content = json.dumps({**candidate.model_dump(), "source": source})
            await asyncio.to_thread(
                self._client.retain,
                bank_id=self._bank_id,
                content=content,
            )

    async def recall(self, query: str, *, limit: int) -> list[MemoryRecord]:
        raw = await asyncio.to_thread(
            self._client.recall,
            bank_id=self._bank_id,
            query=query,
        )
        items = getattr(raw, "results", raw if isinstance(raw, list) else [])
        records: list[MemoryRecord] = []
        for item in list(items)[:limit]:
            if isinstance(item, dict):
                content = item.get("content") or item.get("text") or item.get("memory")
                item_id = item.get("id") or item.get("memory_id")
            else:
                content = (
                    getattr(item, "content", None)
                    or getattr(item, "text", None)
                    or getattr(item, "memory", None)
                )
                item_id = getattr(item, "id", None) or getattr(item, "memory_id", None)
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
                source = str(payload.pop("source", "hindsight"))
                candidate = MemoryCandidate.model_validate(payload)
            except Exception:
                source = "hindsight"
                candidate = MemoryCandidate(
                    predicate="memory",
                    value=content[:2048],
                    confidence=1.0,
                )
            records.append(
                MemoryRecord(
                    id=str(item_id or uuid4().hex),
                    source=source[:256],
                    **candidate.model_dump(),
                )
            )
        return records

    async def list(self, *, limit: int = 100) -> list[MemoryRecord]:
        return await self.recall("user preferences facts", limit=limit)

    async def delete(self, memory_id: str) -> bool:
        raise NotImplementedError("Hindsight record deletion is managed by its service API")

    async def update(self, memory_id: str, candidate: MemoryCandidate) -> bool:
        raise NotImplementedError("Hindsight record editing is managed by its service API")

    async def clear(self) -> int:
        raise NotImplementedError("Hindsight bank deletion is managed by its service API")

    async def close(self) -> None:
        return None


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        subject=row["subject"],
        predicate=row["predicate"],
        value=row["value"],
        confidence=float(row["confidence"]),
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )

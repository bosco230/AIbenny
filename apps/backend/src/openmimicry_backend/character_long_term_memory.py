"""Character-scoped long-term memory service registry.

Each character owns a distinct MemoryService instance.
This module does not create or access SQLite databases.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from openmimicry.memory.service import MemoryService


class CharacterLongTermMemoryManager:
    """Resolve and safely close independently owned memory services."""

    def __init__(
        self,
        services: Mapping[str, MemoryService],
    ) -> None:
        if not services:
            raise ValueError("At least one character service is required")

        if any(
            not isinstance(key, str) or not key.strip()
            for key in services
        ):
            raise ValueError("Character IDs must be non-empty strings")

        copied = dict(services)

        if len({id(service) for service in copied.values()}) != len(copied):
            raise ValueError(
                "Characters must not share a MemoryService instance"
            )

        self._services = copied
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed_ids: set[str] = set()

    def for_character(self, character_id: str) -> MemoryService:
        if self._closing:
            raise RuntimeError("Memory manager is closing or closed")

        try:
            return self._services[character_id]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Unknown character ID: {character_id!r}"
            ) from exc

    async def close_all(self) -> None:
        async with self._close_lock:
            self._closing = True

            pending = {
                character_id: service
                for character_id, service in self._services.items()
                if character_id not in self._closed_ids
            }

            if not pending:
                return

            results = await asyncio.gather(
                *(service.close() for service in pending.values()),
                return_exceptions=True,
            )

            failures: list[Exception] = []
            cancellations: list[BaseException] = []

            for character_id, result in zip(
                pending,
                results,
                strict=True,
            ):
                if isinstance(result, asyncio.CancelledError):
                    cancellations.append(result)
                elif isinstance(result, BaseException):
                    if isinstance(result, Exception):
                        failures.append(result)
                    else:
                        cancellations.append(result)
                else:
                    self._closed_ids.add(character_id)

            if cancellations:
                raise BaseExceptionGroup(
                    "Character memory close was interrupted",
                    cancellations + failures,
                )

            if failures:
                raise ExceptionGroup(
                    "Failed to close character memory services",
                    failures,
                )
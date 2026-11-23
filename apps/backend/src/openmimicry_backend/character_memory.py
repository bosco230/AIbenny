"""Independent short-term conversation memory per character.

This module is not wired into the active conversation pipeline yet.
"""

from __future__ import annotations

from .characters import CHARACTERS, DEFAULT_CHARACTER_ID
from .conversation import ConversationMemory


class CharacterMemoryManager:
    def __init__(self, *, max_turns: int = 4) -> None:
        self._memories = {
            character_id: ConversationMemory(max_turns=max_turns)
            for character_id in CHARACTERS
        }
        self._active_id = DEFAULT_CHARACTER_ID

    @property
    def active_id(self) -> str:
        return self._active_id

    def select(self, character_id: str) -> None:
        if character_id not in self._memories:
            raise ValueError(f"Unknown character: {character_id!r}")
        self._active_id = character_id

    def memory_for(self, character_id: str) -> ConversationMemory:
        try:
            return self._memories[character_id]
        except KeyError as exc:
            raise ValueError(
                f"Unknown character: {character_id!r}"
            ) from exc

    def active_memory(self) -> ConversationMemory:
        return self.memory_for(self._active_id)
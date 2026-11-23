"""Character switching using the shared turn-admission lock.

Not connected to the running application yet.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .character_memory import CharacterMemoryManager
from .conversation import ConversationCoordinator
from .supervisor import RuntimeSupervisor


IdleCheck = Callable[[], Awaitable[bool]]
SpeechIdleCheck = Callable[[], bool]


class CharacterSwitchBusyError(RuntimeError):
    """Switch rejected because the application is not idle."""


class CharacterSwitchController:
    def __init__(
        self,
        *,
        coordinator: ConversationCoordinator,
        memories: CharacterMemoryManager,
        supervisor: RuntimeSupervisor,
        is_idle: IdleCheck,
        is_speech_idle: SpeechIdleCheck,
    ) -> None:
        self._coordinator = coordinator
        self._memories = memories
        self._supervisor = supervisor
        self._is_idle = is_idle
        self._is_speech_idle = is_speech_idle
        self._lock = asyncio.Lock()

    @property
    def active_id(self) -> str:
        return self._memories.active_id

    async def switch(self, character_id: str) -> str:
        async with self._lock:
            target_memory = self._memories.memory_for(character_id)

            if character_id == self.active_id:
                return self.active_id

            if not await self._is_idle():
                raise CharacterSwitchBusyError(
                    "Cannot switch characters while speech is busy"
                )

            def commit() -> None:
                # Final check runs synchronously while the
                # supervisor's turn-admission lock is held.
                if not self._is_speech_idle():
                    raise CharacterSwitchBusyError(
                        "Speech became busy before character switch"
                    )

                self._coordinator.memory = target_memory
                self._memories.select(character_id)

            changed = await self._supervisor.run_when_idle(commit)

            if not changed:
                raise CharacterSwitchBusyError(
                    "Cannot switch characters while a turn is active"
                )

            return self.active_id
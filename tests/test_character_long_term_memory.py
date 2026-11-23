"""Isolated tests for character-scoped long-term memory."""

import asyncio

import pytest

from openmimicry_backend.character_long_term_memory import (
    CharacterLongTermMemoryManager,
)


class FakeMemoryService:
    def __init__(self, fail_close=False):
        self.records = []
        self.closed = 0
        self.fail_close = fail_close

    async def context(self, query):
        return " | ".join(str(item) for item in self.records)

    def observe(self, user_text, assistant_text, *, source):
        self.records.append((user_text, assistant_text, source))

    async def close(self):
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("Simulated close failure")


def test_character_services_are_isolated():
    benny = FakeMemoryService()
    dingdong = FakeMemoryService()

    manager = CharacterLongTermMemoryManager({
        "benny": benny,
        "dingdong": dingdong,
    })

    manager.for_character("benny").observe(
        "Benny fact", "reply", source="test"
    )

    assert len(benny.records) == 1
    assert dingdong.records == []


def test_unknown_character_is_rejected():
    manager = CharacterLongTermMemoryManager({
        "benny": FakeMemoryService(),
    })

    with pytest.raises(ValueError):
        manager.for_character("unknown")


def test_shared_service_is_rejected():
    shared = FakeMemoryService()

    with pytest.raises(ValueError):
        CharacterLongTermMemoryManager({
            "benny": shared,
            "dingdong": shared,
        })


def test_close_all_closes_each_service_once():
    async def scenario():
        benny = FakeMemoryService()
        dingdong = FakeMemoryService()

        manager = CharacterLongTermMemoryManager({
            "benny": benny,
            "dingdong": dingdong,
        })

        await manager.close_all()
        await manager.close_all()

        assert benny.closed == 1
        assert dingdong.closed == 1

        with pytest.raises(RuntimeError):
            manager.for_character("benny")

    asyncio.run(scenario())


def test_failed_close_retries_only_failed_service():
    async def scenario():
        benny = FakeMemoryService()
        dingdong = FakeMemoryService(fail_close=True)

        manager = CharacterLongTermMemoryManager({
            "benny": benny,
            "dingdong": dingdong,
        })

        with pytest.raises(ExceptionGroup):
            await manager.close_all()

        assert benny.closed == 1
        assert dingdong.closed == 1

        with pytest.raises(RuntimeError):
            manager.for_character("benny")

        dingdong.fail_close = False

        await manager.close_all()

        assert benny.closed == 1
        assert dingdong.closed == 2

    asyncio.run(scenario())


def test_lookup_rejected_during_close():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowMemory(FakeMemoryService):
            async def close(self):
                started.set()
                await release.wait()
                await super().close()

        manager = CharacterLongTermMemoryManager({
            "benny": SlowMemory(),
        })

        task = asyncio.create_task(manager.close_all())

        try:
            await started.wait()

            with pytest.raises(RuntimeError):
                manager.for_character("benny")
        finally:
            release.set()
            await task

    asyncio.run(scenario())
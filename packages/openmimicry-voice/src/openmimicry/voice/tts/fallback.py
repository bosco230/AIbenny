"""Azure-first TTS with a lazy Qwen3 fallback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from contextlib import suppress

from openmimicry.core.schemas import TTSConfig

from .azure import AzureTTSAdapter
from .qwen3 import Qwen3TTSAdapter
from .system_command import _collect_text

logger = logging.getLogger(__name__)


class AzureQwen3FallbackTTSAdapter:
    name = "azure-qwen3-fallback"

    def __init__(
        self,
        azure: AzureTTSAdapter,
        qwen3: Qwen3TTSAdapter,
    ) -> None:
        self._azure = azure
        self._qwen3 = qwen3
        self._active = None
        self._ready = asyncio.Event()
        self._speaking = False
        self._generation = 0

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def prepare(self, config: TTSConfig) -> None:
        # Do not preload Qwen3 while Azure is available.
        try:
            await self._azure.prepare(config)
        except Exception as exc:
            logger.warning(
                "Azure TTS preparation failed; Qwen3 remains available as fallback: %s",
                exc,
            )

    async def speak(
        self,
        text_or_stream: str | AsyncIterable[str],
        *,
        config: TTSConfig,
        on_chunk=None,
    ) -> None:
        # BENNY_110E_26V: TTS input timing
        import time as _benny_time
        _benny_collect_start = _benny_time.perf_counter()
        text = await _collect_text(text_or_stream)
        print(f'[BENNY_LATENCY] tts_text_wait={_benny_time.perf_counter()-_benny_collect_start:.3f}s', flush=True)
        if not text.strip():
            return

        self._generation += 1
        generation = self._generation
        self._ready.clear()

        self._speaking = True
        self._active = self._azure

        async def play(adapter) -> None:
            task = asyncio.create_task(
                adapter.speak(text, config=config, on_chunk=on_chunk)
            )
            waiter = getattr(adapter, "wait_until_ready", None)
            ready_task = (
                asyncio.create_task(waiter(timeout_s=180.0))
                if callable(waiter)
                else None
            )
            try:
                if ready_task is not None:
                    done, _ = await asyncio.wait(
                        {task, ready_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if task in done:
                        await task
                        if generation == self._generation:
                            self._ready.set()
                    if ready_task in done and ready_task.result():
                        if generation == self._generation:
                            self._ready.set()
                else:
                    if generation == self._generation:
                        self._ready.set()
                await task
            finally:
                if ready_task is not None:
                    if not ready_task.done():
                        ready_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await ready_task
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

        try:
            try:
                await play(self._azure)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Azure TTS failed; switching to Qwen3: %s", exc
                )
                if generation != self._generation:
                    return
                self._active = self._qwen3
                await self._qwen3.prepare(config)
                await play(self._qwen3)
        finally:
            if generation == self._generation:
                self._speaking = False
                self._active = None

    async def wait_until_ready(
        self, *, timeout_s: float = 30.0
    ) -> bool:
        if not self._speaking and self._ready.is_set():
            self._ready.clear()
        try:
            async with asyncio.timeout(timeout_s):
                await self._ready.wait()
            return True
        except TimeoutError:
            return False

    async def stop(self) -> None:
        self._generation += 1
        self._speaking = False
        adapter = self._active
        self._active = None
        if adapter is not None:
            await adapter.stop()

    async def healthcheck(self) -> bool:
        return await self._azure.healthcheck()

    async def close(self) -> None:
        await self.stop()
        await self._azure.close()
        await self._qwen3.close()
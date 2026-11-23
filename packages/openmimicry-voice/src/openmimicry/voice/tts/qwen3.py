
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import AsyncIterable

from openmimicry.core.schemas import TTSConfig
from openmimicry.voice.tts.system_command import _playback_command

logger = logging.getLogger(__name__)

PYTHON_EXE = (
    r"C:\AI-Girlfriend\cantonese-tts\.venv\Scripts\python.exe"
)

WORKER_SCRIPT = (
    r"C:\AI-Girlfriend\openmimicry-main\openmimicry-main"
    r"\packages\openmimicry-voice\src\openmimicry\voice\workers\qwen3_job.py"
)

_SENTENCE_ENDINGS = "。！？；.!?;\n"
_MAX_CHUNK_LENGTH = 55


class Qwen3TTSAdapter:
    name = "qwen3"

    def __init__(self, startup_timeout_s: float = 180.0):
        self.startup_timeout_s = startup_timeout_s
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._playback_process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._speaking = False
        self._ready_future: asyncio.Future[bool] | None = None
        self._active_files: set[str] = set()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def wait_until_ready(self, *, timeout_s: float = 30.0) -> bool:
        future = self._ready_future
        if future is None:
            return False
        try:
            async with asyncio.timeout(max(0.05, timeout_s)):
                return bool(await asyncio.shield(future))
        except TimeoutError:
            return False

    def _resolve_ready(self, value: bool) -> None:
        future = self._ready_future
        if future is not None and not future.done():
            future.set_result(value)

    async def _read_worker_stderr(
        self,
        stream: asyncio.StreamReader,
    ) -> None:
        try:
            while line := await stream.readline():
                message = line.decode("utf-8", errors="replace").rstrip()
                if not message:
                    continue

                if (
                    "QWEN3 GENERATE:" in message or "QWEN3 DECODE:" in message or "QWEN3 SYNTHESIS:" in message
                    or "QWEN3 CODE PREDICTOR:" in message or "QWEN3 WAV WRITE:" in message
                    or "WORKER RECEIVED TEXT:" in message
                ):
                    logger.info("%s", message)
                else:
                    logger.debug("Qwen3 worker: %s", message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Qwen3 worker stderr reader failed")

    async def prepare(self, config: TTSConfig) -> None:
        """Preload the persistent Qwen3 TTS worker."""
        await self._start_worker()

    async def _start_worker(self) -> None:
        if self._process and self._process.returncode is None:
            return

        self._process = await asyncio.create_subprocess_exec(
            PYTHON_EXE,
            "-u",
            WORKER_SCRIPT,
            "--server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert self._process.stderr is not None
        self._stderr_task = asyncio.create_task(
            self._read_worker_stderr(self._process.stderr),
            name="qwen3.stderr_reader",
        )

        try:
            assert self._process.stdout is not None
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self.startup_timeout_s,
            )
        except asyncio.TimeoutError:
            await self._discard_worker()
            raise RuntimeError("Qwen3 TTS worker startup timed out")

        if not line:
            await self._discard_worker()
            raise RuntimeError("Qwen3 TTS worker failed to start")

        response = json.loads(line.decode("utf-8"))
        if response.get("type") != "ready":
            await self._discard_worker()
            raise RuntimeError(f"Unexpected Qwen3 worker response: {response}")

        logger.info("Qwen3 TTS worker is ready")

    async def _synthesize(self, text: str, output_path: str) -> None:
        await self._start_worker()

        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        request = {
            "type": "synthesize",
            "text": text,
            "output": output_path,
        }

        self._process.stdin.write(
            json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        await self._process.stdin.drain()

        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=300.0,
            )
        except asyncio.TimeoutError:
            await self._discard_worker()
            raise RuntimeError("Qwen3 TTS synthesis timed out")

        if not line:
            await self._discard_worker()
            raise RuntimeError("Qwen3 TTS worker exited unexpectedly")

        response = json.loads(line.decode("utf-8"))
        if response.get("type") != "complete":
            raise RuntimeError(f"Qwen3 TTS synthesis failed: {response}")

    async def _sentence_stream(
        self,
        text_or_stream: str | AsyncIterable[str],
    ):
        if isinstance(text_or_stream, str):
            async def single_text():
                yield text_or_stream

            source = single_text()
        else:
            source = text_or_stream

        buffer = ""

        async for part in source:
            if not part:
                continue

            buffer += part

            while buffer:
                hard_end = next(
                    (
                        index
                        for index, char in enumerate(buffer)
                        if char in _SENTENCE_ENDINGS
                    ),
                    -1,
                )

                comma_end = next(
                    (
                        index
                        for index, char in enumerate(buffer)
                        if char in "，," and index + 1 >= 12
                    ),
                    -1,
                )

                if hard_end >= 0 and (
                    comma_end < 0 or hard_end <= comma_end
                ):
                    end = hard_end
                else:
                    end = comma_end

                if end >= 0:
                    chunk = buffer[:end + 1].strip()
                    buffer = buffer[end + 1:]
                    if chunk:
                        yield chunk
                    continue

                if len(buffer) >= _MAX_CHUNK_LENGTH:
                    split_at = buffer.rfind(" ", 0, _MAX_CHUNK_LENGTH + 1)
                    if split_at < 15:
                        split_at = _MAX_CHUNK_LENGTH

                    chunk = buffer[:split_at].strip()
                    buffer = buffer[split_at:].lstrip()

                    if chunk:
                        yield chunk
                    continue

                break

        if buffer.strip():
            yield buffer.strip()

    async def speak(
        self,
        text_or_stream: str | AsyncIterable[str],
        *,
        config: TTSConfig,
        on_chunk=None,
    ) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            self._ready_future = loop.create_future()
            self._speaking = True
            queue: asyncio.Queue[tuple[str | None, Exception | None]] = (
                asyncio.Queue(maxsize=2)
            )

            sentence_queue: asyncio.Queue[tuple[str | None, Exception | None]] = (
                asyncio.Queue(maxsize=2)
            )

            async def sentence_producer() -> None:
                try:
                    async for sentence in self._sentence_stream(text_or_stream):
                        await sentence_queue.put((sentence, None))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await sentence_queue.put((None, exc))
                else:
                    await sentence_queue.put((None, None))

            async def synthesize_producer() -> None:
                try:
                    while True:
                        sentence, error = await sentence_queue.get()

                        if error is not None:
                            raise error

                        if sentence is None:
                            break

                        with tempfile.NamedTemporaryFile(
                            suffix=".wav",
                            delete=False,
                        ) as temp_file:
                            wave_path = temp_file.name

                        self._active_files.add(wave_path)

                        try:
                            await self._synthesize(sentence, wave_path)
                            await queue.put((wave_path, None))
                        except Exception:
                            self._remove_file(wave_path)
                            raise

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await queue.put((None, exc))
                else:
                    await queue.put((None, None))

            sentence_task = asyncio.create_task(
                sentence_producer(),
                name="qwen3.sentence.producer",
            )
            producer = asyncio.create_task(
                synthesize_producer(),
                name="qwen3.synthesis.producer",
            )

            try:
                while True:
                    wave_path, error = await queue.get()

                    if error is not None:
                        raise error

                    if wave_path is None:
                        break

                    command, environment = _playback_command(Path(wave_path))

                    playback_started = time.perf_counter()
                    logger.info("QWEN3 PLAYBACK START: %s", wave_path)

                    playback = await asyncio.create_subprocess_exec(
                        *command,
                        env=environment,
                    )
                    self._playback_process = playback

                    if not self._ready_future.done():
                        self._resolve_ready(True)

                    await playback.wait()
                    playback_elapsed = time.perf_counter() - playback_started
                    logger.info(
                        "QWEN3 PLAYBACK END: duration=%.3fs",
                        playback_elapsed,
                    )
                    self._playback_process = None

                    if playback.returncode != 0:
                        raise RuntimeError("Qwen3 audio playback failed")

                    self._remove_file(wave_path)

                await producer

                if not self._ready_future.done():
                    self._resolve_ready(False)

            except asyncio.CancelledError:
                sentence_task.cancel()
                producer.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await sentence_task
                with suppress(asyncio.CancelledError, Exception):
                    await producer
                await self._stop_playback()
                raise

            except Exception:
                sentence_task.cancel()
                producer.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await sentence_task
                with suppress(asyncio.CancelledError, Exception):
                    await producer
                await self._stop_playback()
                raise

            finally:
                self._speaking = False
                if not self._ready_future.done():
                    self._resolve_ready(False)

                await self._stop_playback()

                for path in tuple(self._active_files):
                    self._remove_file(path)

    def _remove_file(self, path: str) -> None:
        self._active_files.discard(path)
        with suppress(FileNotFoundError):
            Path(path).unlink()

    async def _stop_playback(self) -> None:
        process = self._playback_process
        self._playback_process = None

        if process is not None and process.returncode is None:
            process.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=3.0)

            if process.returncode is None:
                process.kill()
                await process.wait()

    async def stop(self) -> None:
        await self._stop_playback()
        await self._discard_worker()
        self._speaking = False
        self._resolve_ready(False)

    async def healthcheck(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _discard_worker(self) -> None:
        process = self._process
        self._process = None

        stderr_task = self._stderr_task
        self._stderr_task = None

        if process is not None and process.returncode is None:
            process.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5.0)

        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

        if stderr_task is not None:
            try:
                await asyncio.wait_for(stderr_task, timeout=2.0)
            except asyncio.TimeoutError:
                stderr_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await stderr_task

    async def close(self) -> None:
        await self.stop()
        await self._discard_worker()

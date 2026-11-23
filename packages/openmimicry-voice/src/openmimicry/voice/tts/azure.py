"""Direct ElevenLabs HTTP TTS adapter; no provider SDK dependency."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import wave
from collections.abc import AsyncIterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from openmimicry.core.schemas import TTSConfig

from .lip_sync import pcm_to_mouth_frames
from .system_command import _collect_text, _playback_command

__all__ = ["AzureSpeechSettings", "AzureTTSAdapter"]


_MAX_AUDIO_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class AzureSpeechSettings:
    voice: str = "zh-HK-HiuMaanNeural"
    region: str = "australiaeast"
    api_key_env: str = "AZURE_SPEECH_KEY"
    endpoint: str = "https://australiaeast.tts.speech.microsoft.com/cognitiveservices/v1"


class AzureTTSAdapter:
    name = "azure"

    def __init__(self, settings: AzureSpeechSettings) -> None:
        self._settings = settings
        self._session_api_key: str | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._ready = asyncio.Event()
        self._is_speaking = False
        self._mouth_frames: list[int] = []

    def set_session_api_key(self, value: str) -> None:
        token = value.strip()
        if not token or len(token) > 8192:
            raise ValueError("ElevenLabs token must contain 1 to 8192 characters")
        self._session_api_key = token

    def clear_session_api_key(self) -> None:
        self._session_api_key = None

    @property
    def has_session_api_key(self) -> bool:
        return self._session_api_key is not None

    @property
    def has_credentials(self) -> bool:
        return self.has_session_api_key or bool(os.environ.get(self._settings.api_key_env))

    def credential_status(self) -> dict[str, bool]:
        """Expose credential sources without exposing either credential."""

        return {
            "session": self.has_session_api_key,
            "environment": bool(os.environ.get(self._settings.api_key_env)),
        }

    def _api_key(self) -> str:
        key = self._session_api_key or os.environ.get(self._settings.api_key_env)
        if not key:
            raise RuntimeError(
                f"Azure Speech requires {self._settings.api_key_env} or a session-only token"
            )
        return key

    async def prepare(self, _config: TTSConfig) -> None:
        self._api_key()
        with tempfile.TemporaryDirectory() as tmp:
            _playback_command(Path(tmp) / "preflight.wav")

    async def speak(
        self,
        text_or_stream: str | AsyncIterable[str],
        *,
        config: TTSConfig,
        on_chunk=None,
    ) -> None:
        text = await _collect_text(text_or_stream)
        if not text.strip():
            return
        if len(text) > 10_000:
            raise ValueError("ElevenLabs multilingual v2 input exceeds 10,000 characters")
        await self.stop()
        self._ready = asyncio.Event()
        self._is_speaking = True
        try:
            # BENNY_110E_26V: Azure synthesis timing
            import time as _benny_time
            _benny_azure_start = _benny_time.perf_counter()
            pcm = await asyncio.to_thread(self._synthesize, text)
            print(f'[BENNY_LATENCY] azure_synthesis={_benny_time.perf_counter()-_benny_azure_start:.3f}s', flush=True)
            self._mouth_frames = pcm_to_mouth_frames(pcm)
            if on_chunk is not None:
                on_chunk({
                    "type": "lip_sync.frames",
                    "window_ms": 40,
                    "frames": list(self._mouth_frames),
                })
            with tempfile.TemporaryDirectory(prefix="openmimicry-azure-") as tmp:
                wave_path = Path(tmp) / "utterance.wav"
                _write_pcm_wave(wave_path, pcm, sample_rate=24000)
                command, environment = _playback_command(wave_path)
                _benny_play_start = _benny_time.perf_counter()
                self._process = await asyncio.create_subprocess_exec(
                    *command,
                    env=environment,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._ready.set()
                print(f'[BENNY_LATENCY] azure_playback_start={_benny_time.perf_counter()-_benny_play_start:.3f}s', flush=True)
                _stdout, stderr = await self._process.communicate()
                if self._process.returncode not in {0, None}:
                    raise RuntimeError(
                        "Azure Speech audio playback failed: "
                        + stderr.decode("utf-8", errors="replace")[-1000:]
                    )
        finally:
            self._process = None
            self._is_speaking = False

    def _synthesize(self, text: str) -> bytes:
        from xml.sax.saxutils import escape

        voice = escape(self._settings.voice, {'"': '&quot;'})
        ssml = (
            '<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            'xml:lang="zh-HK">'
            f'<voice name="{voice}">{escape(text)}</voice>'
            '</speak>'
        )
        request = Request(
            self._settings.endpoint,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": self._api_key(),
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm",
                "User-Agent": "OpenMimicry/1.6",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90.0) as response:
                audio = response.read(_MAX_AUDIO_BYTES + 1)
        except HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"Azure Speech returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Azure Speech request failed: {exc}") from exc
        if len(audio) > _MAX_AUDIO_BYTES:
            raise RuntimeError("Azure Speech audio response exceeded 64 MiB")
        if not audio:
            raise RuntimeError("Azure Speech returned an empty audio response")
        return audio
    async def wait_until_ready(self, *, timeout_s: float = 30.0) -> bool:
        try:
            async with asyncio.timeout(timeout_s):
                await self._ready.wait()
            return True
        except TimeoutError:
            return False

    async def stop(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        with suppress(Exception):
            async with asyncio.timeout(1.0):
                await process.wait()
        if process.returncode is None:
            process.kill()

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    async def healthcheck(self) -> bool:
        try:
            self._api_key()
        except RuntimeError:
            return False
        return True

    async def close(self) -> None:
        await self.stop()


def _write_pcm_wave(path: Path, pcm: bytes, *, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)

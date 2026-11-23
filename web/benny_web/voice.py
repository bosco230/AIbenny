"""Azure speech for the browser: TTS returns audio to play, STT takes uploads."""

from __future__ import annotations

import base64
import io
import json
import wave
from html import escape

import httpx
import numpy as np

SAMPLE_RATE = 16000
WINDOW_MS = 40
MAX_UPLOAD_BYTES = 1_200_000  # ~37 s of 16 kHz mono PCM; the page sends <= 15 s


class VoiceError(RuntimeError):
    pass


def mouth_frames(pcm: bytes, *, sample_rate: int = SAMPLE_RATE, window_ms: int = WINDOW_MS) -> list[int]:
    """Signed 16-bit mono PCM -> mouth openness 0-3 per window (for lip-sync)."""

    if len(pcm) < 2:
        return []
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    size = max(1, sample_rate * window_ms // 1000)
    count = (len(samples) + size - 1) // size
    padded = np.zeros(count * size, dtype=np.float32)
    padded[: len(samples)] = samples
    rms = np.sqrt((padded.reshape(count, size) ** 2).mean(axis=1))
    peak = float(rms.max())
    if peak <= 0:
        return [0] * count
    level = rms / peak
    return [0 if v < 0.12 else 1 if v < 0.35 else 2 if v < 0.65 else 3 for v in level.tolist()]


def _pcm_from_wav(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data)) as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise VoiceError("expected 16-bit mono audio")
        return wav.readframes(wav.getnframes())


class AzureSpeech:
    def __init__(self, key: str, region: str, *, timeout_s: float = 30.0) -> None:
        self._key = key
        self._region = region
        self._client = httpx.AsyncClient(timeout=timeout_s)

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def synthesize(self, text: str, voice: str) -> dict[str, object]:
        """Speak ``text``; returns base64 WAV plus lip-sync frames."""

        ssml = (
            "<speak version='1.0' xml:lang='zh-HK'>"
            f"<voice name='{escape(voice, quote=True)}'>{escape(text)}</voice></speak>"
        )
        response = await self._client.post(
            f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1",
            content=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
                "User-Agent": "benny-web",
            },
        )
        if response.status_code >= 400:
            raise VoiceError(f"Azure TTS {response.status_code}")
        audio = response.content
        return {
            "audio": "data:audio/wav;base64," + base64.b64encode(audio).decode("ascii"),
            "frames": mouth_frames(_pcm_from_wav(audio)),
            "window_ms": WINDOW_MS,
        }

    async def transcribe(self, wav_bytes: bytes) -> str:
        """Cantonese speech-to-text for a short 16 kHz mono WAV upload."""

        if len(wav_bytes) > MAX_UPLOAD_BYTES:
            raise VoiceError("recording too long")
        _pcm_from_wav(wav_bytes)  # validates the format
        response = await self._client.post(
            f"https://{self._region}.stt.speech.microsoft.com/speech/recognition/conversation/"
            "cognitiveservices/v1?language=zh-HK&format=simple",
            content=wav_bytes,
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
        )
        if response.status_code >= 400:
            raise VoiceError(f"Azure STT {response.status_code}")
        payload = json.loads(response.text or "{}")
        if payload.get("RecognitionStatus") != "Success":
            return ""
        return str(payload.get("DisplayText") or "").strip()

    async def close(self) -> None:
        await self._client.aclose()

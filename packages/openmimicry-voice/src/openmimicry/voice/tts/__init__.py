"""TTS adapters."""

from __future__ import annotations

from .fallback import AzureQwen3FallbackTTSAdapter

from .azure import AzureSpeechSettings, AzureTTSAdapter

from .base import TTSAdapter
from .chatterbox import ChatterboxSettings, ChatterboxTTSAdapter
from .elevenlabs import ElevenLabsSettings, ElevenLabsTTSAdapter
from .isolated_piper import (
    IsolatedPiperSettings,
    IsolatedPiperTTSAdapter,
    IsolatedTTSUnavailable,
)
from .realtimetts_adapter import RealtimeTTSAdapter, RealtimeTTSSettings
from .system_command import SystemCommandTTSAdapter, SystemTTSUnavailable
from .qwen3 import Qwen3TTSAdapter

__all__ = [
    "AzureSpeechSettings",
    "AzureTTSAdapter",
    "ChatterboxSettings",
    "ChatterboxTTSAdapter",
    "ElevenLabsSettings",
    "ElevenLabsTTSAdapter",
    "IsolatedPiperSettings",
    "IsolatedPiperTTSAdapter",
    "IsolatedTTSUnavailable",
    "RealtimeTTSAdapter",
    "RealtimeTTSSettings",
    "SystemCommandTTSAdapter",
    "SystemTTSUnavailable",
    "Qwen3TTSAdapter",
    "TTSAdapter",
]

"""Web edition settings, all from environment variables (see web/.env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_ROOT.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    persona: Path
    azure_voice: str


@dataclass(frozen=True)
class Settings:
    passcode: str
    session_secret: str
    secure_cookies: bool
    openrouter_key: str
    chat_model: str
    helper_model: str
    openrouter_url: str
    azure_key: str
    azure_region: str
    ollama_url: str
    embedding_model: str
    data_dir: Path
    config_dir: Path
    characters_dir: Path
    # Usage limits.
    messages_per_10min: int
    messages_per_day: int
    tts_chars_per_day: int
    tts_chars_per_day_total: int
    stt_requests_per_day: int
    history_turns: int
    characters: dict[str, Character] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        config_dir = Path(os.environ.get("BENNY_WEB_CONFIG", WEB_ROOT / "config"))
        data_dir = Path(os.environ.get("BENNY_WEB_DATA", WEB_ROOT / "data"))
        characters = {
            "benny": Character("benny", "Benny", config_dir / "personas" / "benny.yml", "zh-HK-HiuMaanNeural"),
            "dingdong": Character("dingdong", "叮當", config_dir / "personas" / "dingdong.yml", "zh-HK-WanLungNeural"),
        }
        return cls(
            passcode=os.environ.get("WEB_PASSCODE", ""),
            session_secret=os.environ.get("SESSION_SECRET", ""),
            secure_cookies=os.environ.get("SECURE_COOKIES", "1") != "0",
            openrouter_key=os.environ.get("OPENROUTER_API_KEY", ""),
            chat_model=os.environ.get("CHAT_MODEL", "anthropic/claude-haiku-5.5"),
            helper_model=os.environ.get("HELPER_MODEL", "qwen/qwen3.7-flash"),
            openrouter_url=os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
            azure_key=os.environ.get("AZURE_SPEECH_KEY", ""),
            azure_region=os.environ.get("AZURE_SPEECH_REGION", "australiaeast"),
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            embedding_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
            data_dir=data_dir,
            config_dir=config_dir,
            characters_dir=Path(os.environ.get("BENNY_WEB_CHARACTERS", REPO_ROOT / "characters")),
            messages_per_10min=_int("LIMIT_MESSAGES_PER_10MIN", 30),
            messages_per_day=_int("LIMIT_MESSAGES_PER_DAY", 300),
            tts_chars_per_day=_int("LIMIT_TTS_CHARS_PER_DAY", 6000),
            tts_chars_per_day_total=_int("LIMIT_TTS_CHARS_PER_DAY_TOTAL", 60000),
            stt_requests_per_day=_int("LIMIT_STT_PER_DAY", 200),
            history_turns=_int("HISTORY_TURNS", 10),
            characters=characters,
        )

    def problems(self) -> list[str]:
        """Missing settings that stop the web edition from working safely."""

        issues = []
        if len(self.passcode) < 6:
            issues.append("WEB_PASSCODE must be at least 6 characters")
        if len(self.session_secret) < 32:
            issues.append("SESSION_SECRET must be at least 32 random characters")
        if not self.openrouter_key:
            issues.append("OPENROUTER_API_KEY is not set")
        return issues

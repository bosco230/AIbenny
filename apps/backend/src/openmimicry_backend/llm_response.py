"""Structured assistant reply parsing with a safe plain-text fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ParsedAssistantReply",
    "PersonalitySettings",
    "load_personality",
    "parse_assistant_reply",
]


DEFAULT_EMOTIONS = (
    "neutral",
    "happy",
    "sad",
    "angry",
    "confused",
    "focused",
    "worried",
)
DEFAULT_ACTIONS = ("idle", "wave", "nod", "celebrate", "think", "none")
_BUILTIN_PERSONALITY = Path("config/personality.yml")
_LOCAL_PERSONALITY = Path("~/.openmimicry/personality.yml")


@dataclass(frozen=True)
class PersonalitySettings:
    system_prompt: str
    structured_avatar_output: bool
    allowed_emotions: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    cue_duration_ms: int


@dataclass(frozen=True)
class ParsedAssistantReply:
    text: str
    emotion: str = "neutral"
    action: str = "idle"
    intensity: float = 0.6
    duration_ms: int = 1800
    structured: bool = False


def load_personality(path: str | os.PathLike[str] | None = None) -> PersonalitySettings:
    configured = path or os.environ.get("OPENMIMICRY_PERSONALITY_PATH")
    if configured is not None:
        candidate = Path(configured).expanduser()
    else:
        local = _LOCAL_PERSONALITY.expanduser()
        candidate = local if local.is_file() else _BUILTIN_PERSONALITY
    data: dict[str, Any] = {}
    if candidate.is_file():
        try:
            loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    behaviour = data.get("behavior")
    if not isinstance(behaviour, dict):
        behaviour = {}
    emotions = _string_tuple(behaviour.get("allowed_emotions"), DEFAULT_EMOTIONS)
    actions = _string_tuple(behaviour.get("allowed_actions"), DEFAULT_ACTIONS)
    duration = _bounded_int(behaviour.get("cue_duration_ms"), 1800, 250, 15000)
    structured = bool(behaviour.get("structured_avatar_output", True))
    base_prompt = str(data.get("system_prompt") or "You are OpenMimicry, a helpful companion.")

    if structured:
        contract = (
            "\n\nReturn exactly one JSON object with this shape: "
            '{"reply":"your answer","emotion":"one allowed emotion",'
            '"action":"one allowed action","intensity":0.0}. '
            f"Allowed emotions: {', '.join(emotions)}. "
            f"Allowed actions: {', '.join(actions)}. "
            "Do not wrap the JSON in Markdown and do not add other keys."
        )
        base_prompt += contract

    return PersonalitySettings(
        system_prompt=base_prompt,
        structured_avatar_output=structured,
        allowed_emotions=emotions,
        allowed_actions=actions,
        cue_duration_ms=duration,
    )


def parse_assistant_reply(raw: str, settings: PersonalitySettings) -> ParsedAssistantReply:
    """Parse the JSON envelope; never expose malformed JSON to the user."""

    cleaned = raw.strip()
    if not cleaned:
        return ParsedAssistantReply(text="", duration_ms=settings.cue_duration_ms)
    if not settings.structured_avatar_output:
        return ParsedAssistantReply(text=cleaned, duration_ms=settings.cue_duration_ms)

    candidate = _strip_code_fence(cleaned)
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return ParsedAssistantReply(text=cleaned, duration_ms=settings.cue_duration_ms)
    if not isinstance(payload, dict):
        return ParsedAssistantReply(text=cleaned, duration_ms=settings.cue_duration_ms)

    reply = payload.get("reply", payload.get("text", payload.get("message")))
    if not isinstance(reply, str) or not reply.strip():
        return ParsedAssistantReply(text=cleaned, duration_ms=settings.cue_duration_ms)

    emotion = str(payload.get("emotion") or "neutral").strip().lower()
    if emotion not in settings.allowed_emotions:
        emotion = "neutral"
    action = str(payload.get("action") or "idle").strip().lower()
    if action not in settings.allowed_actions:
        action = "idle"
    try:
        intensity = float(payload.get("intensity", 0.6))
    except (TypeError, ValueError):
        intensity = 0.6

    return ParsedAssistantReply(
        text=reply.strip(),
        emotion=emotion,
        action=action,
        intensity=max(0.0, min(1.0, intensity)),
        duration_ms=settings.cue_duration_ms,
        structured=True,
    )


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _string_tuple(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return fallback
    cleaned = tuple(str(item).strip().lower() for item in value if str(item).strip())
    return cleaned or fallback


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))

class IncrementalJSONReplyExtractor:
    """Incrementally decode the reply string from the expected JSON envelope."""

    def __init__(self) -> None:
        self._buffer = ""
        self._started = False
        self._finished = False
        self._pending_escape = ""
        self._pending_high_surrogate = ""

    def feed(self, chunk: str) -> str:
        if self._finished:
            return ""

        self._buffer += chunk
        output: list[str] = []

        if not self._started:
            marker = '"reply"'
            position = self._buffer.find(marker)
            if position < 0:
                self._buffer = self._buffer[-(len(marker) - 1):]
                return ""

            remainder = self._buffer[position + len(marker):]
            colon = remainder.find(":")
            if colon < 0:
                self._buffer = self._buffer[position:]
                return ""

            value = remainder[colon + 1:].lstrip()
            if not value:
                return ""
            if not value.startswith('"'):
                self._finished = True
                return ""

            self._buffer = value[1:]
            self._started = True

        index = 0
        while index < len(self._buffer):
            char = self._buffer[index]

            if self._pending_escape:
                self._pending_escape += char
                index += 1
                escape = self._pending_escape

                if escape == "\\":
                    continue
                if len(escape) == 2 and escape[1] in '"\\/bfnrt':
                    output.append(json.loads('"' + escape + '"'))
                    self._pending_escape = ""
                    continue
                if len(escape) >= 2 and escape[1] == "u":
                    if len(escape) < 6:
                        continue
                    if len(escape) > 6:
                        raise ValueError("Invalid JSON Unicode escape")
                    code = int(escape[2:], 16)
                    if 0xD800 <= code <= 0xDBFF:
                        self._pending_high_surrogate = escape
                    elif 0xDC00 <= code <= 0xDFFF:
                        high = self._pending_high_surrogate
                        if high:
                            output.append(json.loads('"' + high + escape + '"'))
                            self._pending_high_surrogate = ""
                        else:
                            output.append(chr(code))
                    else:
                        if self._pending_high_surrogate:
                            output.append(json.loads('"' + self._pending_high_surrogate + '"'))
                            self._pending_high_surrogate = ""
                        output.append(chr(code))
                    self._pending_escape = ""
                    continue
                if len(escape) >= 2:
                    raise ValueError("Invalid JSON escape")
                continue

            if char == '"':
                self._finished = True
                index += 1
                break

            if char == "\\":
                self._pending_escape = "\\"
                index += 1
                continue

            if ord(char) < 0x20:
                raise ValueError("Unescaped control character in JSON string")

            if self._pending_high_surrogate:
                output.append(json.loads('"' + self._pending_high_surrogate + '"'))
                self._pending_high_surrogate = ""

            output.append(char)
            index += 1

        self._buffer = self._buffer[index:]
        return "".join(output)

    def finish(self) -> str:
        """Flush a pending high surrogate; incomplete JSON escapes are discarded."""
        if self._pending_high_surrogate:
            value = json.loads('"' + self._pending_high_surrogate + '"')
            self._pending_high_surrogate = ""
            return value
        self._pending_escape = ""
        self._finished = True
        return ""

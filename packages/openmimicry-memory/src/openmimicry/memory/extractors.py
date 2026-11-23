"""Fast deterministic extraction plus an optional independent LLM pass."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol

from .models import MemoryCandidate

__all__ = ["DeterministicExtractor", "LLMExtractor", "MemoryLLM"]


class MemoryLLM(Protocol):
    async def complete(self, prompt: str) -> str: ...


class DeterministicExtractor:
    """Extract only explicit first-person facts; never infer sensitive data."""

    _patterns: Sequence[tuple[str, re.Pattern[str]]] = (
        ("name", re.compile(r"\bmy name is\s+([^.!?]{1,80})", re.IGNORECASE)),
        ("location", re.compile(r"\bi (?:live|reside) in\s+([^.!?]{1,120})", re.IGNORECASE)),
        (
            "likes",
            re.compile(r"\bi (?:really )?(?:like|love|enjoy)\s+([^.!?]{1,180})", re.IGNORECASE),
        ),
        ("dislikes", re.compile(r"\bi (?:dislike|hate)\s+([^.!?]{1,180})", re.IGNORECASE)),
        ("preference", re.compile(r"\bi prefer\s+([^.!?]{1,180})", re.IGNORECASE)),
    )

    def extract(self, user_text: str, _assistant_text: str) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        for predicate, pattern in self._patterns:
            for match in pattern.finditer(user_text):
                value = " ".join(match.group(1).strip(" ,;:\t\r\n").split())
                if value:
                    candidates.append(
                        MemoryCandidate(predicate=predicate, value=value, confidence=1.0)
                    )
        return candidates


class LLMExtractor:
    """Use a separately selected LLM and reject every non-schema result."""

    def __init__(self, llm: MemoryLLM) -> None:
        self._llm = llm

    async def extract(self, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        # BENNY_USER_ONLY_MEMORY_EXTRACTION_110D3
        prompt = (
            "Extract only durable facts or preferences explicitly stated "
            "by the USER in the current message. "
            "Do not extract facts from assistant responses, prior answers, "
            "questions, guesses, or quoted statements. "
            "If the user is only asking a question or recalling what the "
            "assistant said, return an empty memories list. "
            "Do not infer sensitive attributes. "
            "Return JSON only as "
            '{"memories":[{"predicate":"...","value":"...","confidence":0.0}]}. '
            f"User message: {user_text}"
        )
        raw = await self._llm.complete(prompt)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        items = payload.get("memories", []) if isinstance(payload, dict) else []
        # BENNY_MEMORY_VALIDATION_110E8
        # Conservative validation before retaining LLM-extracted facts.
        results: list[MemoryCandidate] = []

        question_markers = ("?", "\uFF1F", "\u5E7E\u591A", "\u591A\u5C11", "\u8A18\u5514\u8A18\u5F97")
        is_question = any(marker in user_text for marker in question_markers)

        for item in items[:12] if isinstance(items, list) else []:
            try:
                candidate = MemoryCandidate.model_validate(item)
            except Exception:
                continue

            # A question alone must not create a durable memory.
            if is_question:
                continue

            # A lucky number must be numeric and explicitly present
            # in the user's current message.
            if candidate.predicate in {
                "test_lucky_number",
                "test_lucky_numbers",
                "lucky_number",
            }:
                value = candidate.value.strip()

                if not value.isascii() or not value.isdecimal():
                    continue

                numbers = re.findall(r"(?<!\d)\d+(?!\d)", user_text)

                if value not in numbers:
                    continue

            results.append(candidate)

        return results

"""Fast deterministic extraction plus an optional independent LLM pass."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from .models import MemoryCandidate

__all__ = ["DeterministicExtractor", "LLMExtractor", "MemoryLLM"]

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_EVENT_VALUE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*\S")


_WEEKDAY_CHARS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_RELATIVE_DAYS = (("大後日", 3), ("後日", 2), ("後天", 2), ("聽日", 1), ("明日", 1), ("明天", 1), ("今日", 0), ("今天", 0))
_WEEKDAY_PATTERN = re.compile(
    r"(下下|下個|下|今個|呢個|這個|今|本)?\s*(?:星期|禮拜|礼拜|週|周)([一二三四五六日天])"
)


def resolve_spoken_date(text: str, today: date) -> date | None:
    """Resolve one Cantonese relative date ("下星期三", "聽日") deterministically.

    Returns ``None`` when the text has no date expression or more than one,
    so the caller only overrides the LLM when the answer is unambiguous.
    """

    found: set[date] = set()
    for match in _WEEKDAY_PATTERN.finditer(text):
        prefix, day_char = match.group(1) or "", match.group(2)
        monday = today - timedelta(days=today.weekday())
        if prefix in ("下下",):
            monday += timedelta(days=14)
        elif prefix in ("下個", "下"):
            monday += timedelta(days=7)
        target = monday + timedelta(days=_WEEKDAY_CHARS[day_char])
        if not prefix and target < today:
            target += timedelta(days=7)  # bare "星期一" means the next one
        found.add(target)
    remaining = _WEEKDAY_PATTERN.sub("", text)
    for word, offset in _RELATIVE_DAYS:
        if word in remaining:
            found.add(today + timedelta(days=offset))
            remaining = remaining.replace(word, "")
    return found.pop() if len(found) == 1 else None


def _parse_json_object(raw: str) -> Any:
    """Parse model output that may carry a <think> block or code fences."""

    text = raw.split("</think>", 1)[1] if "</think>" in raw else raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


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

    # Fixed categories keep the store tidy; the old free-form prompt produced
    # dozens of one-off predicates such as user_emotion or user_last_message.
    ALLOWED_PREDICATES = frozenset(
        {
            "name",
            "nickname",
            "likes",
            "dislikes",
            "job",
            "workplace",
            "family",
            "partner",
            "friend",
            "pet",
            "location",
            "birthday",
            "health",
            "habit",
            "goal",
            "skill",
            "event",
            "fact",
            "test_lucky_number",
            "lucky_number",
        }
    )

    async def extract(self, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        # BENNY_USER_ONLY_MEMORY_EXTRACTION_110D3 (rewritten for Phase 2)
        today = date.today()
        # Small models are poor at date arithmetic, so hand them a calendar.
        calendar = "\u3001".join(
            f"{day.isoformat()}={_WEEKDAYS[day.weekday()]}"
            for day in (today + timedelta(days=offset) for offset in range(15))
        )
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(days=7)
        prompt = (
            f"\u4ECA\u65E5\u4FC2 {today.isoformat()}\uFF08{_WEEKDAYS[today.weekday()]}\uFF09\u3002\n"
            f"\u4E4B\u5F8C\u5169\u500B\u661F\u671F\u5605\u65E5\u66C6\uFF1A{calendar}\u3002\n"
            f"\u300C\u4ECA\u500B\u661F\u671F\uFF0F\u5462\u500B\u661F\u671FX\u300D\u6307 {this_monday.isoformat()} \u958B\u59CB\u55F0\u500B\u661F\u671F\uFF1B"
            f"\u300C\u4E0B\u661F\u671FX\u300D\u6307 {next_monday.isoformat()} \u958B\u59CB\u55F0\u500B\u661F\u671F\uFF1B"
            "\u300C\u807D\u65E5\u300D\u4FC2\u4ECA\u65E5\u52A0\u4E00\u65E5\uFF0C\u300C\u5F8C\u65E5\u300D\u4FC2\u52A0\u5169\u65E5\u3002\u65E5\u671F\u4E00\u5B9A\u8981\u55BA\u65E5\u66C6\u5165\u9762\u63C0\uFF0C\u661F\u671F\u5E7E\u8981\u5C0D\u5F97\u4E0A\u3002\n"
            "\u4F60\u8CA0\u8CAC\u7531\u300C\u4F7F\u7528\u8005\u300D\u4ECA\u6B21\u8B1B\u5605\u8AAA\u8A71\u5165\u9762\uFF0C\u62BD\u53D6\u503C\u5F97\u9577\u671F\u8A18\u4F4F\u5605\u4E8B\u5BE6\u3002\n"
            "\u898F\u5247\uFF1A\n"
            "1. \u53EA\u62BD\u53D6\u4F7F\u7528\u8005\u660E\u78BA\u8B1B\u51FA\u3001\u95DC\u65BC\u4F62\u81EA\u5DF1\u5605\u9577\u671F\u4E8B\u5BE6\uFF1B"
            "\u5514\u597D\u62BD\u53D6\u52A9\u624B\u8B1B\u5605\u5622\u3001\u554F\u984C\u3001\u4F30\u8A08\u6216\u8005\u5F15\u8FF0\u3002\n"
            "2. \u5514\u597D\u8A18\u4E00\u6642\u5605\u60C5\u7DD2\u3001\u6253\u62DB\u547C\u3001\u8981\u6C42\u52A9\u624B\u505A\u5605\u5622\u3001\u4ECA\u6B21\u50BE\u7DCA\u54A9\u8A71\u984C\u3002\n"
            "3. predicate \u53EA\u53EF\u4EE5\u4FC2\uFF1Aname, nickname, likes, dislikes, job, workplace, "
            "family, partner, friend, pet, location, birthday, health, habit, goal, "
            "skill, event, fact\u3002\n"
            "4. event \u4FC2\u6709\u65E5\u671F\u5605\u5C07\u4F86\u6216\u8005\u6700\u8FD1\u5605\u4E8B\uFF08\u4F8B\u5982\u9762\u8A66\u3001\u65C5\u884C\u3001\u7747\u91AB\u751F\u3001\u751F\u65E5\u6703\uFF09\u3002"
            "value \u5FC5\u9808\u5BEB\u6210\u300CYYYY-MM-DD \u63CF\u8FF0\u300D\uFF0C\u5C07\u300C\u807D\u65E5\u300D\u300C\u4E0B\u661F\u671F\u4E09\u300D\u7B49\u63DB\u7B97\u6210\u5BE6\u969B\u65E5\u671F\uFF1B"
            "\u5187\u8B1B\u65E5\u671F\u5C31\u5514\u597D\u7576 event\u3002\n"
            "5. family/partner/friend/pet \u5605 value \u8981\u5305\u57CB\u95DC\u4FC2\u540C\u540D\uFF0C\u4F8B\u5982\u300C\u4E0A\u53F8\uFF1A\u9EC3\u751F\u300D\u300C\u8C93\uFF1A\u54AA\u54AA\u300D\u3002\n"
            "6. value \u7528\u4F7F\u7528\u8005\u539F\u672C\u5605\u7528\u5B57\uFF08\u7E41\u9AD4\u4E2D\u6587\uFF09\uFF0C\u7C21\u77ED\u3002\n"
            "7. \u5982\u679C\u4F7F\u7528\u8005\u53EA\u4FC2\u554F\u554F\u984C\u3001\u6216\u8005\u53EB\u4F60\u56DE\u61B6\uFF0C\u56DE\u50B3\u7A7A list\u3002\n"
            "\u53EA\u56DE\u50B3 JSON\uFF1A"
            '{"memories":[{"predicate":"...","value":"...","confidence":0.0}]}\n'
            f"\u4F7F\u7528\u8005\u8AAA\u8A71\uFF1A{user_text}"
        )
        raw = await self._llm.complete(prompt)
        payload = _parse_json_object(raw)
        items = payload.get("memories", []) if isinstance(payload, dict) else []
        # BENNY_MEMORY_VALIDATION_110E8
        # Conservative validation before retaining LLM-extracted facts.
        results: list[MemoryCandidate] = []

        # A pure question ("\u4F60\u8A18\u5514\u8A18\u5F97\u6211\u937E\u610F\u98F2\u54A9\uFF1F") must not create memories,
        # but speech-to-text often appends "?" to statements, so only treat
        # text as a pure question when it says nothing about the user.
        question_markers = ("?", "\uFF1F", "\u5E7E\u591A", "\u591A\u5C11", "\u8A18\u5514\u8A18\u5F97")
        is_question = any(marker in user_text for marker in question_markers) and (
            "\u6211" not in user_text or "\u8A18\u5514\u8A18\u5F97" in user_text
        )

        for item in items[:12] if isinstance(items, list) else []:
            try:
                candidate = MemoryCandidate.model_validate(item)
            except Exception:
                continue

            # A question alone must not create a durable memory.
            if is_question:
                continue

            predicate = candidate.predicate.strip().casefold()
            if predicate not in self.ALLOWED_PREDICATES:
                continue
            if predicate == "event":
                if not _EVENT_VALUE.match(candidate.value):
                    continue
                spoken = resolve_spoken_date(user_text, today)
                if spoken is not None:
                    description = candidate.value.strip()[10:].strip(" :：-")
                    candidate = candidate.model_copy(
                        update={"value": f"{spoken.isoformat()} {description}"}
                    )
            if candidate.predicate != predicate:
                candidate = candidate.model_copy(update={"predicate": predicate})

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

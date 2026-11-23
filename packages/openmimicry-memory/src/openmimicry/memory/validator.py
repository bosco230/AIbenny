"""Conservative, time-aware validation for Benny memory candidates."""

import re

from .models import MemoryCandidate


# BENNY_MEMORY_VALIDATOR_110E9Z3

_VALUE_ALIASES = {
    "coffee": ("\u5496\u5561", "coffee"),
    "tea": ("\u8336", "tea"),
    "milk_tea": ("\u5976\u8336", "milk tea"),
}

_NEGATIVE = (
    "\u5514\u937E\u610F",
    "\u4E0D\u559C\u6B61",
    "don't like",
)

_AMBIGUOUS = (
    "\u5514\u4FC2\u5514",
    "\u4E0D\u662F\u4E0D",
)

_THIRD_PARTY = (
    "\u670B\u53CB\u8A71",
    "\u670B\u53CB\u8AAA",
    "\u670B\u53CB",
    "\u4EBA\u5730\u8A71",
    "\u4ED6\u8AAA",
    "\u5979\u8AAA",
)

_PAST = (
    "\u4EE5\u524D",
    "\u904E\u53BB",
    "\u4E4B\u524D",
    "used to",
)

_CURRENT = (
    "\u800C\u5BB6",
    "\u73FE\u5728",
    "\u4ECD\u7136",
    "\u4F9D\u7136",
    "now",
    "still",
)

_DIRECT_POSITIVE = (
    "\u6211\u937E\u610F",
    "\u6211\u559C\u6B61",
    "i like ",
)

_GENERAL_POSITIVE = (
    "\u937E\u610F",
    "\u559C\u6B61",
    "like ",
)

_SPLIT = re.compile(
    r"[\uFF0C\u3002,;]|"
    r"\u4F46\u4FC2|"
    r"\u4F46\u662F|"
    r"\u4F46"
)


class MemoryValidator:
    """Accept only explicitly supported current user preferences."""

    def validate(
        self,
        candidate: MemoryCandidate,
        user_text: str,
    ) -> bool:
        if candidate.predicate.casefold() != "likes":
            return False

        value = candidate.value.strip().casefold()
        aliases = _VALUE_ALIASES.get(value)

        if aliases is None:
            return False

        clauses = _SPLIT.split(user_text.casefold())

        for clause in clauses:
            clause = clause.strip()

            if not clause:
                continue

            if any(x in clause for x in _THIRD_PARTY):
                continue

            if any(x in clause for x in _AMBIGUOUS):
                continue

            if any(x in clause for x in _NEGATIVE):
                continue

            if any(x in clause for x in _PAST):
                continue

            if not self._contains_value(clause, aliases):
                continue

            direct = any(
                x in clause for x in _DIRECT_POSITIVE
            )

            current = (
                any(x in clause for x in _CURRENT)
                and any(x in clause for x in _GENERAL_POSITIVE)
            )

            if direct or current:
                return True

        return False

    @staticmethod
    def _contains_value(
        clause: str,
        aliases: tuple[str, ...],
    ) -> bool:
        for alias in aliases:
            if alias == "\u8336":
                if (
                    "\u5976\u8336" in clause
                    or "\u7D05\u8336" in clause
                ):
                    continue

            if alias.isascii():
                pattern = (
                    r"(?<![a-z])"
                    + re.escape(alias)
                    + r"(?![a-z])"
                )
                if re.search(pattern, clause):
                    return True
            elif alias in clause:
                return True

        return False

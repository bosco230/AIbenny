
"""Conservative preference validation prototype for Benny."""
import re

# BENNY_MEMORY_VALIDATOR_110E9ZE_V2

ALIASES = {
    "coffee": ("\u5496\u5561", "coffee"),
    "tea": ("\u8336", "tea"),
    "milk_tea": ("\u5976\u8336", "milk tea"),
}

NEGATIVE = (
    "\u5514\u937E\u610F",
    "\u4E0D\u559C\u6B61",
    "don't like",
)

POSITIVE = (
    "\u937E\u610F",
    "\u559C\u6B61",
    "like ",
)

THIRD_PARTY = (
    "\u670B\u53CB",
    "\u4EBA\u5730",
    "\u4F62",
    "\u4ED6",
    "\u5979",
)

JOINT = (
    "\u6211\u540C\u4F62\u90FD",
    "\u6211\u540C\u4ED6\u90FD",
    "\u6211\u540C\u5979\u90FD",
)

PAST = (
    "\u4EE5\u524D",
    "\u4E4B\u524D",
    "\u904E\u53BB",
    "used to",
)

CURRENT = (
    "\u800C\u5BB6",
    "\u73FE\u5728",
    "\u4ECD\u7136",
    "\u4F9D\u7136",
    "now",
    "still",
)

AMBIGUOUS = (
    "\u5514\u4FC2\u5514",
    "\u4E0D\u662F\u4E0D",
)

SPLIT = re.compile(
    r"[\uFF0C\u3002,;]|"
    r"\u4F46\u4FC2|"
    r"\u4F46\u662F|"
    r"\u4F46|"
    r"\bbut\b"
)


def contains_target(clause, value):
    aliases = ALIASES.get(value)

    if aliases is None:
        return False

    for alias in aliases:
        if alias == "\u8336":
            remaining = clause.replace("\u5976\u8336", "")
            remaining = remaining.replace("\u7D05\u8336", "")
            if "\u8336" not in remaining:
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


def validate_preference(value, text):
    if value not in ALIASES:
        return False

    decision = None
    self_context = False

    for clause in SPLIT.split(text.casefold()):
        clause = clause.strip()

        if not clause:
            continue

        joint = any(x in clause for x in JOINT)

        if any(x in clause for x in THIRD_PARTY) and not joint:
            self_context = False
            continue

        explicit_self = (
            "\u6211" in clause
            or joint
            or re.search(r"\bi\b", clause) is not None
        )

        if explicit_self:
            self_context = True

        if not contains_target(clause, value):
            continue

        if any(x in clause for x in PAST):
            continue

        if any(x in clause for x in AMBIGUOUS):
            continue

        if unsafe_clause(clause):
            continue

        if not self_context:
            continue

        if any(x in clause for x in NEGATIVE):
            decision = False
            continue

        if any(x in clause for x in POSITIVE):
            decision = True

    return decision is True


# BENNY_MEMORY_VALIDATOR_110E9ZH_V3

UNSAFE_MARKERS = (
    "\u5982\u679C",
    "\u5047\u5982",
    "\u5047\u8A2D",
    "\u53EF\u80FD",
    "\u6216\u8A31",
    "\u5514\u80AF\u5B9A",
    "\u4E0D\u78BA\u5B9A",
    "\u55CE",
    "\u5462",
    "\uFF1F",
    "?",
    "maybe",
    "perhaps",
)

def unsafe_clause(clause):
    if any(marker in clause for marker in UNSAFE_MARKERS):
        return True

    if re.search(r"\b(if|might|may|perhaps|maybe)\b", clause):
        return True

    if re.search(r"\b(do|does|did|would|could)\s+i\b", clause):
        return True

    return False

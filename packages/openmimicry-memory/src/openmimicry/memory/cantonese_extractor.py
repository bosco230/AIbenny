"""Conservative Cantonese preference extraction."""

import re

from .models import MemoryCandidate


class CantoneseExtractor:
    """Extract simple, explicit first-person Cantonese likes."""

    _negative_pattern = re.compile(
        r"^\u6211"
        r"(?:\u5514\u937e\u610f|\u5514\u559c\u6b61|\u8a0e\u53ad)"
        r"(?P<action>\u98f2|\u98df|\u73a9)"
        r"(?P<value>[\u3400-\u9fffA-Za-z0-9_]{1,40})"
        r"[.!。！]?$"
    )

    _pattern = re.compile(
        r"^\u6211"
        r"(?:\u937e\u610f|\u559c\u6b61)"
        r"(?P<action>\u98f2|\u98df|\u73a9)"
        r"(?P<value>[\u3400-\u9fffA-Za-z0-9_]{1,40})"
        r"[.!。！]?$"
    )

    _blocked = (
        '\u5514',
        '\u4e0d',
        '\u7121',
        '\u6c92',
        '\u4ee5\u524d',
        '\u66fe\u7d93',
        '\u5982\u679c',
        '\u5047\u5982',
        '\u53ef\u80fd',
        '\u6703',
        '\u55ce',
        '\u5462',
        '\u5497',
        '\u4fc2\u5514\u4fc2',
        '\u540c',
        '\u548c',
        '\u8207',
        '\u53ca',
        '\u6216',
        '\u9084\u662f',
        '\u4f46',
        '\u800c\u4e14',
        '\u56e0\u70ba',
        '\u54a9',
        '\u5440',
    )

    _category_conflicts = {
        "\u98f2": {
            "\u6d17\u8863\u6a5f",
            "\u96fb\u8166",
            "\u9ad8\u723e\u592b",
        },
        "\u98df": {
            "\u6d17\u8863\u6a5f",
            "\u96fb\u8166",
        },
        "\u73a9": {
            "\u5496\u5561",
            "\u5976\u8336",
        },
    }

    def extract(
        self,
        user_text: str,
        _assistant_text: str = "",
    ) -> list[MemoryCandidate]:
        if not isinstance(user_text, str):
            return []

        text = user_text.strip()

        if any(ch in text for ch in (
            "?", "\uff1f", "\uff0c", ",",
            ";", "\uff1b", "\n",
        )):
            return []

        match = self._negative_pattern.fullmatch(text)
        predicate = "dislikes"

        if match is None:
            match = self._pattern.fullmatch(text)
            predicate = "likes"

        if match is None:
            return []

        action = match.group("action")
        value = match.group("value")

        if any(word in value for word in self._blocked):
            return []

        if value in self._category_conflicts[action]:
            return []

        return [
            MemoryCandidate(
                subject="user",
                predicate=predicate,
                value=value,
                confidence=1.0,
            )
        ]

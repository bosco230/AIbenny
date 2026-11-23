"""Read-only topic-based Bible retrieval for Benny."""

from __future__ import annotations

from .bible_search import lookup, find_reference

TOPICS = {
    "饒恕": {
        "keywords": (
            "饒恕", "原諒", "寬恕", "寬容",
            "唔肯原諒", "放低怨恨",
        ),
        "verses": (
            ("MAT", 6, 14),
            ("EPH", 4, 32),
        ),
    },
    "信心": {
        "keywords": (
            "信心", "信靠", "相信上帝",
            "相信神", "信仰",
        ),
        "verses": (
            ("HEB", 11, 1),
            ("JAM", 2, 17),
        ),
    },
    "愛": {
        "keywords": (
            "愛", "愛心", "愛人",
            "上帝愛", "神愛", "彼此相愛",
        ),
        "verses": (
            ("1CO", 13, 4),
            ("JOH", 3, 16),
        ),
    },
    "禱告": {
        "keywords": (
            "禱告", "祈禱", "祈求",
            "點樣禱告", "點樣祈禱",
        ),
        "verses": (
            ("MAT", 6, 6),
            ("PHI", 4, 6),
        ),
    },
    "憂慮": {
        "keywords": (
            "憂慮", "擔心", "掛慮",
            "焦慮", "煩惱", "驚將來",
            "擔心未來", "擔心將來",
        ),
        "verses": (
            ("MAT", 6, 25),
            ("MAT", 6, 34),
        ),
    },
}


def detect_topic(question: str):
    """Return the first matching Bible topic, or None."""
    question = question.strip()

    if not question:
        return None

    bible_context = (
        "聖經", "經文", "上帝", "耶穌", "基督",
        "教會", "信仰", "屬靈", "天父",
    )

    has_bible_context = any(
        word in question for word in bible_context
    )

    explicit_prayer_request = (
        any(word in question for word in ("禱告", "祈禱"))
        and any(
            word in question
            for word in ("點樣", "如何", "應該", "教我", "教導")
        )
    )

    if not has_bible_context and not explicit_prayer_request:
        return None

    for topic, config in TOPICS.items():
        for keyword in config["keywords"]:
            if keyword in question:
                return topic

    return None


def retrieve_topic(database, question: str):
    """Return a topic and its verified verses from SQLite.

    Explicit chapter-and-verse requests take priority.
    """

    if find_reference(database, question) is not None:
        return None

    topic = detect_topic(question)

    if topic is None:
        return None

    verses = []

    for book, chapter, number in TOPICS[topic]["verses"]:
        verse = lookup(database, book, chapter, number)

        if verse is not None:
            verses.append(verse)

    if not verses:
        return None

    return {
        "topic": topic,
        "verses": verses,
    }
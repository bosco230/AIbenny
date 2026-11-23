"""Read-only local Bible lookup for Benny.

Source: Traditional Chinese Union Version (cmn-cu89t).
This module does not modify the database or chat history.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

BOOK_NAMES = {
    "創世記": "GEN",
    "出埃及記": "EXO",
    "利未記": "LEV",
    "民數記": "NUM",
    "申命記": "DEU",
    "約書亞記": "JOS",
    "士師記": "JDG",
    "路得記": "RUT",
    "撒母耳記上": "1SA",
    "撒母耳記下": "2SA",
    "列王紀上": "1KI",
    "列王紀下": "2KI",
    "歷代志上": "1CH",
    "歷代志下": "2CH",
    "以斯拉記": "EZR",
    "尼希米記": "NEH",
    "以斯帖記": "EST",
    "約伯記": "JOB",
    "詩篇": "PSA",
    "箴言": "PRO",
    "傳道書": "ECC",
    "雅歌": "SOL",
    "以賽亞書": "ISA",
    "耶利米書": "JER",
    "耶利米哀歌": "LAM",
    "以西結書": "EZE",
    "但以理書": "DAN",
    "何西阿書": "HOS",
    "約珥書": "JOE",
    "阿摩司書": "AMO",
    "俄巴底亞書": "OBA",
    "約拿書": "JON",
    "彌迦書": "MIC",
    "那鴻書": "NAH",
    "哈巴谷書": "HAB",
    "西番雅書": "ZEP",
    "哈該書": "HAG",
    "撒迦利亞書": "ZEC",
    "瑪拉基書": "MAL",
    "馬太福音": "MAT",
    "馬可福音": "MAR",
    "路加福音": "LUK",
    "約翰福音": "JOH",
    "使徒行傳": "ACT",
    "羅馬書": "ROM",
    "哥林多前書": "1CO",
    "哥林多後書": "2CO",
    "加拉太書": "GAL",
    "以弗所書": "EPH",
    "腓立比書": "PHI",
    "歌羅西書": "COL",
    "帖撒羅尼迦前書": "1TH",
    "帖撒羅尼迦後書": "2TH",
    "提摩太前書": "1TI",
    "提摩太後書": "2TI",
    "提多書": "TIT",
    "腓利門書": "PHM",
    "希伯來書": "HEB",
    "雅各書": "JAM",
    "彼得前書": "1PE",
    "彼得後書": "2PE",
    "約翰一書": "1JO",
    "約翰二書": "2JO",
    "約翰三書": "3JO",
    "猶大書": "JUD",
    "啟示錄": "REV",
}

CODE_NAMES = {code: name for name, code in BOOK_NAMES.items()}

_REFERENCE_PATTERN = re.compile(
    r"(\d{0,1}[A-Z]{2,3}|[\u3400-\u9fff]+)"
    r"\s*(\d{1,3})\s*[:：]\s*(\d{1,3})"
)


def _connect(database: str | Path) -> sqlite3.Connection:
    path = Path(database).resolve(strict=True)
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.execute("PRAGMA query_only=ON")
    return connection


def lookup(
    database: str | Path,
    book: str,
    chapter: int,
    verse: int,
) -> dict | None:
    """Return one verse by book code or Chinese book name."""
    code = BOOK_NAMES.get(book, book.upper())

    with _connect(database) as connection:
        row = connection.execute(
            """
            SELECT text
            FROM verses
            WHERE book=? AND chapter=? AND verse=?
            """,
            (code, chapter, verse),
        ).fetchone()

    if row is None:
        return None

    return {
        "book": code,
        "book_name": CODE_NAMES.get(code, code),
        "chapter": chapter,
        "verse": verse,
        "text": row[0],
    }


def search(
    database: str | Path,
    keyword: str,
    limit: int = 8,
) -> list[dict]:
    """Find verses containing an exact Chinese substring."""
    keyword = keyword.strip()

    if not keyword:
        return []

    limit = max(1, min(int(limit), 30))

    with _connect(database) as connection:
        rows = connection.execute(
            """
            SELECT book, chapter, verse, text
            FROM verses
            WHERE instr(text, ?) > 0
            ORDER BY id
            LIMIT ?
            """,
            (keyword, limit),
        ).fetchall()

    return [
        {
            "book": book,
            "book_name": CODE_NAMES.get(book, book),
            "chapter": chapter,
            "verse": verse,
            "text": text,
        }
        for book, chapter, verse, text in rows
    ]



def find_reference(
    database: str | Path,
    question: str,
) -> dict | None:
    """Find a Bible reference inside a natural-language question."""
    names = sorted(
        BOOK_NAMES,
        key=len,
        reverse=True,
    )

    names.extend(
        sorted(CODE_NAMES, key=len, reverse=True)
    )

    for name in names:
        pattern = re.compile(
            re.escape(name)
            + r"\s*(\d{1,3})\s*[:：]\s*(\d{1,3})"
        )

        match = pattern.search(question)

        if match is None:
            continue

        chapter = int(match.group(1))
        verse = int(match.group(2))

        result = lookup(
            database,
            name,
            chapter,
            verse,
        )

        if result is not None:
            return result

    return None

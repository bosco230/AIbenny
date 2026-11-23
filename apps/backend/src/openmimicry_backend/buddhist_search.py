"""Read-only Buddhist scripture retrieval for Benny and 叮當.

Database: data/buddhist/buddhist.sqlite, built by
scripts/build_buddhist_db.py from CBETA Taishō XML (心經, 金剛經,
阿彌陀經, 法華經普門品).

Three ways a question finds scripture, in order:
1. an exact phrase from a sutra ("色即是空", "應無所住而生其心");
2. a sutra name ("金剛經講咩") -> that sutra's key passages;
3. a topic word (無常, 放下, 恐懼, 往生, 慈悲 ...) -> curated passages.
Returned text is always the database's original wording.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

__all__ = ["BuddhistPassage", "build_context", "find_passages"]

_MAX_CHARS = 900

# Distinctive substrings that locate the key passages of each sutra.
_KEY_PASSAGES: dict[str, tuple[str, ...]] = {
    "T08n0251": (),  # 心經 is short: always the whole text
    "T08n0235": ("應無所住而生其心", "凡所有相，皆是虛妄", "一切有為法"),
    "T12n0366": ("從是西方過十萬億佛土", "執持名號", "不可以少善根福德因緣"),
    "T09n0262": ("以何因緣名觀世音", "一心稱名，觀世音菩薩即時觀其音聲", "慈眼視眾生"),
}

# Topic words -> (sutra code, locating substring).
_TOPICS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("無常", "放下", "執著", "執着", "睇開", "看開", "夢幻"), "T08n0235", "一切有為法"),
    (("住相", "著相", "放低", "自在"), "T08n0235", "應無所住而生其心"),
    (("恐懼", "驚", "擔心", "焦慮", "煩惱", "掛礙", "罣礙"), "T08n0251", "心無罣礙"),
    (("空", "五蘊", "色即是空"), "T08n0251", "色不異空"),
    (("往生", "淨土", "念佛", "死亡", "過身", "臨終", "極樂"), "T12n0366", "執持名號"),
    (("觀音", "觀世音", "求救", "危難", "苦難", "慈悲"), "T09n0262", "一心稱名，觀世音菩薩即時觀其音聲"),
)

_BUDDHIST_HINTS = ("佛", "經", "菩薩", "觀音", "觀世音", "阿彌陀", "般若", "禪", "涅槃", "因果", "業", "輪迴", "修行")
# Famous short lines people quote on their own ("色即是空係咩意思？").
# Everyday idioms that also occur in the sutras (不可思議, 一心) are
# deliberately absent so ordinary chat never triggers scripture.
_FAMOUS_LINES = (
    "色即是空", "空即是色", "色不異空", "五蘊皆空", "心無罣礙", "諸法空相", "不生不滅",
    "不垢不淨", "不增不減", "度一切苦厄", "揭帝", "揭諦", "應無所住", "如夢幻泡影",
    "夢幻泡影", "一切有為法", "凡所有相", "皆是虛妄", "如露亦如電", "執持名號",
    "極樂世界", "慈眼視眾生", "南無阿彌陀佛",
)
_CJK_RUN = re.compile(r"[㐀-鿿豈-﫿]+")


@dataclass(frozen=True)
class BuddhistPassage:
    code: str
    sutra: str
    translator: str
    section: str
    seq: int
    text: str

    @property
    def reference(self) -> str:
        section = f"·{self.section}" if self.section and self.section not in self.sutra else ""
        return f"《{self.sutra}》{section}（{self.translator}，第{self.seq}段）"


def _connect(database: str | Path) -> sqlite3.Connection:
    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


_SELECT = (
    "SELECT p.code, s.name AS sutra, s.translator, p.section, p.seq, p.text "
    "FROM passages p JOIN sutras s ON s.code = p.code "
)


def _row(row: sqlite3.Row) -> BuddhistPassage:
    return BuddhistPassage(
        row["code"], row["sutra"], row["translator"], row["section"], row["seq"], row["text"]
    )


def _containing(db: sqlite3.Connection, code: str | None, needle: str) -> list[BuddhistPassage]:
    if code:
        rows = db.execute(_SELECT + "WHERE p.code = ? AND instr(p.text, ?) > 0 ORDER BY p.seq", (code, needle))
    else:
        rows = db.execute(_SELECT + "WHERE instr(p.text, ?) > 0 ORDER BY p.code, p.seq", (needle,))
    return [_row(r) for r in rows]


def _phrase_match(db: sqlite3.Connection, question: str, min_len: int) -> list[BuddhistPassage]:
    """Longest run of question characters that appears verbatim in a sutra."""

    for run in sorted(_CJK_RUN.findall(question), key=len, reverse=True):
        for size in range(min(len(run), 16), min_len - 1, -1):
            for start in range(0, len(run) - size + 1):
                hits = _containing(db, None, run[start : start + size])
                if hits:
                    return hits[:2]
    return []


def _aliases(db: sqlite3.Connection) -> list[tuple[str, str]]:
    pairs = []
    for row in db.execute("SELECT code, aliases FROM sutras"):
        pairs.extend((alias, row["code"]) for alias in row["aliases"].split("|"))
    return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


def find_passages(database: str | Path, question: str) -> list[BuddhistPassage]:
    text = question.strip()
    if not text:
        return []
    try:
        db = _connect(database)
    except (OSError, sqlite3.Error):
        return []
    with db:
        hinted = any(hint in text for hint in _BUDDHIST_HINTS + _FAMOUS_LINES)
        mentioned = next((code for alias, code in _aliases(db) if alias in text), None)

        # 1. Quoted phrase. Without a Buddhist hint require a longer match so
        #    ordinary chat never pulls in scripture by accident.
        phrase = _phrase_match(db, text, 4 if (hinted or mentioned) else 6)
        if phrase:
            return phrase

        # 2. Named sutra -> key passages.
        if mentioned:
            if not _KEY_PASSAGES.get(mentioned):
                return [_row(r) for r in db.execute(_SELECT + "WHERE p.code = ? ORDER BY p.seq", (mentioned,))]
            found: list[BuddhistPassage] = []
            for needle in _KEY_PASSAGES[mentioned]:
                for passage in _containing(db, mentioned, needle)[:1]:
                    if passage not in found:
                        found.append(passage)
            return found

        # 3. Topic words (only when the question sounds Buddhist).
        if hinted:
            for words, code, needle in _TOPICS:
                if any(word in text for word in words):
                    return _containing(db, code, needle)[:1]
    return []


def build_context(passages: list[BuddhistPassage]) -> str | None:
    if not passages:
        return None
    lines: list[str] = []
    used = 0
    for passage in passages:
        body = passage.text
        if used + len(body) > _MAX_CHARS:
            body = body[: max(0, _MAX_CHARS - used)] + "……"
        lines.append(f"出處：{passage.reference}\n經文：{body}")
        used += len(body)
        if used >= _MAX_CHARS:
            break
    return (
        "以下係本地大正藏佛經參考資料（CBETA 電子版）。"
        "引用經文時必須逐字保留原文用字同標點，唔好改寫、翻譯或者改做廣東話；"
        "清楚標示經名，並分清原文同解釋。經文以外用自然廣東話解釋。"
        "保留原有角色個性及回覆格式。\n\n" + "\n\n".join(lines)
    )

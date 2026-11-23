"""Finance-novel library shared by Benny and 叮當.

Drop your own .txt / .epub / .pdf books into ``data/novels/inbox/``. They are
imported at backend start (and from the dashboard): split into chapters,
cut into ~500-character passages and indexed with the same local embedding
model as long-term memory (bge-m3 via Ollama).

During chat the library supplies, for whichever companion is active:
* passages relevant to the question (restricted to a named book if any),
* never beyond the chapter the user has reached (spoiler guard),
* a short library list with reading progress, for recommendations.

Saying "我睇到《書名》第12章" records progress automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import sqlite3
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname as posix_dirname
from posixpath import join as posix_join
from posixpath import normpath as posix_normpath
from typing import Any
from xml.etree import ElementTree as ET

__all__ = [
    "Book",
    "NovelLibrary",
    "chinese_number",
    "extract_book",
    "split_passages",
]

_log = logging.getLogger(__name__)

SUPPORTED = (".txt", ".epub", ".pdf")
PASSAGE_TARGET = 500
PASSAGE_MAX = 800
CONTEXT_MAX_CHARS = 1500

_CHAPTER_LINE = re.compile(
    r"^\s*(?:第\s*[0-9０-９零〇一二兩三四五六七八九十百千]+\s*[章回節卷部篇集]"
    r"|chapter\s+[0-9ivxlc]+\b|CHAPTER\s+[0-9IVXLC]+\b|楔子|序章|尾聲|後記)[^\n]{0,40}$",
    re.IGNORECASE | re.MULTILINE,
)
_NOVEL_HINTS = (
    "小說", "本書", "呢本", "嗰本", "書入面", "書中", "主角", "劇情", "角色", "人物",
    "情節", "結局", "章", "作者", "書庫", "書單", "推介", "推薦", "下一本", "睇咩書", "讀咩書",
)
_LIBRARY_HINTS = ("書庫", "書單", "推介", "推薦", "下一本", "睇咩書", "讀咩書", "有咩書", "睇到邊", "讀到邊")
_SPOILER_OK = ("劇透都得", "唔怕劇透", "睇晒", "讀完", "睇完", "結局係", "全書")
_PROGRESS = re.compile(
    r"(?:睇到|讀到|看到)\s*(?:《(?P<t1>[^》]{1,40})》)?\s*(?:嘅|的)?\s*"
    r"第\s*(?P<n>[0-9０-９零〇一二兩三四五六七八九十百千]+)\s*[章回]"
)
_PROGRESS_TITLE_FIRST = re.compile(
    r"《(?P<t>[^》]{1,40})》\s*(?:我)?\s*(?:睇到|讀到|看到)\s*第\s*"
    r"(?P<n>[0-9０-９零〇一二兩三四五六七八九十百千]+)\s*[章回]"
)

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def chinese_number(text: str) -> int | None:
    """Parse "12", "１２", "十二", "一百零三" -> int."""

    text = text.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for char in text:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            total += (current or 1) * _CN_UNITS[char]
            current = 0
        else:
            return None
    total += current
    return total or None


# ---------------------------------------------------------------- extraction


@dataclass(frozen=True)
class ExtractedBook:
    title: str
    author: str
    chapters: list[tuple[str, str]]  # (chapter title, text)


class _HTMLText(HTMLParser):
    _BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "section", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading: str | None = None
        self._in_heading = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        if tag in ("h1", "h2", "h3") and self.heading is None:
            self._in_heading = True
            self.heading = ""
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3"):
            self._in_heading = False
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._in_heading and self.heading is not None:
            self.heading += data.strip()


def _clean(text: str) -> str:
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n").replace("　", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            if encoding == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    from charset_normalizer import from_bytes

    best = from_bytes(raw).best()
    if best is not None:
        return str(best)
    return raw.decode("big5", errors="replace")


def _split_chapters(text: str) -> list[tuple[str, str]]:
    text = _clean(text)
    marks = list(_CHAPTER_LINE.finditer(text))
    if len(marks) < 2:
        return [("全文", text)] if text else []
    chapters: list[tuple[str, str]] = []
    prefix = text[: marks[0].start()].strip()
    if len(prefix) > 200:
        chapters.append(("前言", prefix))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end() : end].strip()
        if body:
            chapters.append((mark.group(0).strip(), body))
    return chapters


def _epub(path: Path) -> ExtractedBook:
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile"))
        opf_path = rootfile.get("full-path", "")
        opf = ET.fromstring(archive.read(opf_path))
        base = posix_dirname(opf_path)

        def first(tag: str) -> str:
            for element in opf.iter():
                if element.tag.endswith("}" + tag) and (element.text or "").strip():
                    return element.text.strip()
            return ""

        manifest = {
            item.get("id"): item.get("href")
            for item in opf.iter()
            if item.tag.endswith("item") and item.get("id") and item.get("href")
        }
        spine = [ref.get("idref") for ref in opf.iter() if ref.tag.endswith("itemref")]
        chapters: list[tuple[str, str]] = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            name = posix_normpath(posix_join(base, href.split("#")[0]))
            try:
                markup = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            parser = _HTMLText()
            parser.feed(markup)
            body = _clean("".join(parser.parts))
            if len(body) < 50:
                continue
            title = (parser.heading or "").strip() or body.split("\n", 1)[0][:30]
            chapters.append((title, body))
    return ExtractedBook(first("title") or path.stem, first("creator"), chapters)


def _pdf(path: Path) -> ExtractedBook:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    meta = reader.metadata or {}
    title = str(getattr(meta, "title", None) or path.stem)
    author = str(getattr(meta, "author", None) or "")
    return ExtractedBook(title, author, _split_chapters(text))


def extract_book(path: Path) -> ExtractedBook:
    suffix = path.suffix.casefold()
    if suffix == ".epub":
        return _epub(path)
    if suffix == ".pdf":
        return _pdf(path)
    if suffix == ".txt":
        return ExtractedBook(path.stem, "", _split_chapters(_decode(path.read_bytes())))
    raise ValueError(f"unsupported book format: {path.suffix}")


def split_passages(text: str, *, target: int = PASSAGE_TARGET, maximum: int = PASSAGE_MAX) -> list[str]:
    """Cut a chapter into ~target-character passages at paragraph/sentence ends."""

    pieces: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n")):
        if not paragraph:
            continue
        while len(paragraph) > maximum:
            cut = max(
                (paragraph.rfind(mark, 0, maximum) for mark in "。！？!?；.\n"),
                default=-1,
            )
            cut = cut + 1 if cut > target // 2 else maximum
            pieces.append(paragraph[:cut])
            paragraph = paragraph[cut:].strip()
        if paragraph:
            pieces.append(paragraph)
    passages: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > target:
            passages.append(current)
            current = piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        passages.append(current)
    return passages


# ------------------------------------------------------------------ library


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    author: str
    file_name: str
    chapters: int
    passages: int
    characters: int
    progress: int | None
    indexed: int
    imported_at: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
    file_name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    chapters INTEGER NOT NULL, characters INTEGER NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    number INTEGER NOT NULL, title TEXT NOT NULL, PRIMARY KEY (book_id, number)
);
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter INTEGER NOT NULL, seq INTEGER NOT NULL, text TEXT NOT NULL,
    model TEXT, vector BLOB
);
CREATE INDEX IF NOT EXISTS idx_passages_book ON passages(book_id, chapter, seq);
CREATE TABLE IF NOT EXISTS progress (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    chapter INTEGER NOT NULL, updated_at TEXT NOT NULL
);
"""


class NovelLibrary:
    def __init__(
        self,
        database: str | Path,
        inbox: str | Path,
        embedder: Any | None,
        *,
        threshold: float = 0.45,
        margin: float = 0.08,
    ) -> None:
        self._db_path = Path(database)
        self.inbox = Path(inbox)
        self._embedder = embedder
        self._threshold = threshold
        self._margin = margin
        self._lock = asyncio.Lock()
        self._matrix: Any = None
        self._meta: list[tuple[int, int, int]] = []  # (passage id, book id, chapter)
        self._index_dirty = True

    # ----------------------------------------------------------- storage

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(_SCHEMA)
        return connection

    def _run(self, fn, *args):  # type: ignore[no-untyped-def]
        connection = self._connect()
        try:
            with connection:
                return fn(connection, *args)
        finally:
            connection.close()

    # ------------------------------------------------------------ books

    async def books(self) -> list[Book]:
        return await asyncio.to_thread(self._run, _list_books)

    async def delete(self, book_id: int) -> bool:
        removed = await asyncio.to_thread(self._run, _delete_book, book_id)
        self._index_dirty = True
        return bool(removed)

    async def set_progress(self, book_id: int, chapter: int | None) -> None:
        await asyncio.to_thread(self._run, _set_progress, book_id, chapter)

    async def import_inbox(self) -> list[dict[str, Any]]:
        """Import every new supported file in the inbox, then embed passages."""

        self.inbox.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        async with self._lock:
            for path in sorted(self.inbox.iterdir()):
                if not path.is_file() or path.suffix.casefold() not in SUPPORTED:
                    continue
                try:
                    results.append(await asyncio.to_thread(self._import_file, path))
                except Exception as exc:  # one bad file must not stop the rest
                    _log.warning("NOVEL_IMPORT_FAILED %s: %s", path.name, exc)
                    results.append({"file": path.name, "status": "failed", "error": str(exc)[:300]})
            await self._embed_missing()
        return results

    def _import_file(self, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = self._run(lambda c: c.execute("SELECT title FROM books WHERE sha256 = ?", (digest,)).fetchone())
        if existing:
            return {"file": path.name, "status": "already imported", "title": existing["title"]}
        book = extract_book(path)
        if not book.chapters:
            raise ValueError("no readable text found (scanned PDF or DRM-protected file?)")
        passages = [
            (number, seq, text)
            for number, (_, body) in enumerate(book.chapters, start=1)
            for seq, text in enumerate(split_passages(body), start=1)
        ]
        title = re.sub(r"[《》]", "", book.title).strip() or path.stem
        book_id = self._run(_insert_book, title, book.author, path.name, digest, book.chapters, passages)
        self._index_dirty = True
        _log.info("NOVEL_IMPORTED %s chapters=%d passages=%d", title, len(book.chapters), len(passages))
        return {
            "file": path.name, "status": "imported", "id": book_id, "title": title,
            "chapters": len(book.chapters), "passages": len(passages),
        }

    async def _embed_missing(self, batch: int = 16) -> int:
        if self._embedder is None:
            return 0
        import numpy as np

        done = 0
        while True:
            rows = await asyncio.to_thread(self._run, _unembedded, batch)
            if not rows:
                break
            vectors = await self._embedder.embed([row["text"] for row in rows])
            payload = []
            for row, vector in zip(rows, vectors, strict=True):
                array = np.asarray(vector, dtype=np.float32)
                norm = float(np.linalg.norm(array)) or 1.0
                payload.append(((array / norm).tobytes(), self._embedder.model, row["id"]))
            await asyncio.to_thread(self._run, _store_vectors, payload)
            done += len(payload)
        if done:
            self._index_dirty = True
        return done

    # ---------------------------------------------------------- retrieval

    async def _load_index(self) -> None:
        if not self._index_dirty:
            return
        import numpy as np

        rows = await asyncio.to_thread(self._run, _all_vectors)
        if rows:
            self._matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
            self._meta = [(r["id"], r["book_id"], r["chapter"]) for r in rows]
        else:
            self._matrix, self._meta = None, []
        self._index_dirty = False

    async def context(self, question: str) -> str | None:
        """System context for this turn, or None when books are irrelevant."""

        text = question.strip()
        if not text:
            return None
        books = await self.books()
        if not books:
            return None
        notes: list[str] = []
        mentioned = _mentioned_book(books, text)

        # "我睇到《X》第12章" -> remember progress.
        progress_update = _parse_progress(text, books, mentioned)
        if progress_update is not None:
            book, chapter = progress_update
            await self.set_progress(book.id, chapter)
            notes.append(f"（已記低：使用者讀到《{book.title}》第 {chapter} 章。）")
            books = await self.books()
            mentioned = next(b for b in books if b.id == book.id)

        hinted = mentioned is not None or any(h in text for h in _NOVEL_HINTS)
        if not hinted:
            return None

        sections: list[str] = []
        if any(h in text for h in _LIBRARY_HINTS) or mentioned is None:
            sections.append("書庫入面嘅金融小說（同另一位伴侶共用）：\n" + "\n".join(
                f"- 《{b.title}》{('，' + b.author) if b.author else ''}，共 {b.chapters} 章；"
                + (f"使用者讀到第 {b.progress} 章" if b.progress else "未記錄閱讀進度")
                for b in books
            ))

        spoiler_ok = any(w in text for w in _SPOILER_OK)
        passages = await self._search(text, mentioned, spoiler_ok=spoiler_ok)
        if passages:
            lines = []
            used = 0
            for title, chapter_no, chapter_title, body in passages:
                if used >= CONTEXT_MAX_CHARS:
                    break
                body = body[: CONTEXT_MAX_CHARS - used]
                used += len(body)
                lines.append(f"出處：《{title}》第 {chapter_no} 章 {chapter_title}\n原文：{body}")
            sections.append(
                "以下係書庫原文片段（只供參考，引用時要逐字、簡短，並標明書名同章數）：\n\n"
                + "\n\n".join(lines)
            )
        if mentioned is not None and mentioned.progress and not spoiler_ok:
            sections.append(
                f"防劇透：使用者讀到《{mentioned.title}》第 {mentioned.progress} 章，"
                "唔好講之後章節嘅情節或者結局，除非佢自己要求。"
            )
        if not sections:
            return None
        return "\n\n".join(notes + sections)

    async def _search(
        self, question: str, book: Book | None, *, spoiler_ok: bool, limit: int = 3
    ) -> list[tuple[str, int, str, str]]:
        if self._embedder is None:
            return []
        await self._load_index()
        if self._matrix is None:
            return []
        import numpy as np

        vector = np.asarray((await self._embedder.embed([question]))[0], dtype=np.float32)
        vector /= float(np.linalg.norm(vector)) or 1.0
        scores = self._matrix @ vector
        progress = {b.id: b.progress for b in await self.books()}
        candidates = []
        for index in np.argsort(-scores)[:200]:
            pid, book_id, chapter = self._meta[int(index)]
            if book is not None and book_id != book.id:
                continue
            limit_chapter = progress.get(book_id)
            if limit_chapter and not spoiler_ok and chapter > limit_chapter:
                continue
            candidates.append((float(scores[int(index)]), pid))
            if len(candidates) >= limit:
                break
        if not candidates or candidates[0][0] < self._threshold:
            return []
        floor = max(self._threshold, candidates[0][0] - self._margin)
        ids = [pid for score, pid in candidates if score >= floor]
        return await asyncio.to_thread(self._run, _passage_rows, ids)


# ------------------------------------------------------------- sql helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_books(c: sqlite3.Connection) -> list[Book]:
    rows = c.execute(
        """SELECT b.*, p.chapter AS progress,
                  (SELECT COUNT(*) FROM passages x WHERE x.book_id = b.id) AS passages,
                  (SELECT COUNT(*) FROM passages x WHERE x.book_id = b.id AND x.vector IS NOT NULL) AS indexed
           FROM books b LEFT JOIN progress p ON p.book_id = b.id ORDER BY b.title"""
    ).fetchall()
    return [
        Book(r["id"], r["title"], r["author"], r["file_name"], r["chapters"], r["passages"],
             r["characters"], r["progress"], r["indexed"], r["imported_at"])
        for r in rows
    ]


def _insert_book(
    c: sqlite3.Connection,
    title: str,
    author: str,
    file_name: str,
    digest: str,
    chapters: Sequence[tuple[str, str]],
    passages: Sequence[tuple[int, int, str]],
) -> int:
    cursor = c.execute(
        "INSERT INTO books(title, author, file_name, sha256, chapters, characters, imported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, author, file_name, digest, len(chapters), sum(len(t) for _, t in chapters), _now()),
    )
    book_id = int(cursor.lastrowid or 0)
    c.executemany(
        "INSERT INTO chapters(book_id, number, title) VALUES (?, ?, ?)",
        [(book_id, number, name[:120]) for number, (name, _) in enumerate(chapters, start=1)],
    )
    c.executemany(
        "INSERT INTO passages(book_id, chapter, seq, text) VALUES (?, ?, ?, ?)",
        [(book_id, chapter, seq, text) for chapter, seq, text in passages],
    )
    return book_id


def _delete_book(c: sqlite3.Connection, book_id: int) -> int:
    return c.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount


def _set_progress(c: sqlite3.Connection, book_id: int, chapter: int | None) -> None:
    if chapter is None:
        c.execute("DELETE FROM progress WHERE book_id = ?", (book_id,))
    else:
        c.execute(
            "INSERT OR REPLACE INTO progress(book_id, chapter, updated_at) VALUES (?, ?, ?)",
            (book_id, chapter, _now()),
        )


def _unembedded(c: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return c.execute("SELECT id, text FROM passages WHERE vector IS NULL LIMIT ?", (limit,)).fetchall()


def _store_vectors(c: sqlite3.Connection, payload: list[tuple[bytes, str, int]]) -> None:
    c.executemany("UPDATE passages SET vector = ?, model = ? WHERE id = ?", payload)


def _all_vectors(c: sqlite3.Connection) -> list[sqlite3.Row]:
    return c.execute("SELECT id, book_id, chapter, vector FROM passages WHERE vector IS NOT NULL").fetchall()


def _passage_rows(c: sqlite3.Connection, ids: list[int]) -> list[tuple[str, int, str, str]]:
    out = []
    for pid in ids:
        row = c.execute(
            """SELECT b.title, p.chapter, ch.title AS chapter_title, p.text FROM passages p
               JOIN books b ON b.id = p.book_id
               LEFT JOIN chapters ch ON ch.book_id = p.book_id AND ch.number = p.chapter
               WHERE p.id = ?""",
            (pid,),
        ).fetchone()
        if row:
            out.append((row["title"], row["chapter"], row["chapter_title"] or "", row["text"]))
    return out


def _mentioned_book(books: Sequence[Book], text: str) -> Book | None:
    quoted = re.findall(r"《([^》]{1,40})》", text)
    for book in sorted(books, key=lambda b: len(b.title), reverse=True):
        if any(q == book.title or q in book.title or book.title in q for q in quoted):
            return book
        if len(book.title) >= 2 and book.title in text:
            return book
    return None


def _parse_progress(text: str, books: Sequence[Book], mentioned: Book | None) -> tuple[Book, int] | None:
    match = _PROGRESS_TITLE_FIRST.search(text) or _PROGRESS.search(text)
    if not match:
        return None
    chapter = chinese_number(match.group("n"))
    if not chapter:
        return None
    title = match.groupdict().get("t") or match.groupdict().get("t1")
    book = _mentioned_book(books, f"《{title}》") if title else mentioned
    if book is None and len(books) == 1:
        book = books[0]
    if book is None:
        return None
    return book, min(chapter, book.chapters)

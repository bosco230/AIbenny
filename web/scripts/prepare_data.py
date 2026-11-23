"""Prepare web/data from the desktop edition's data (read-only copy).

Copies the Bible and Buddhist databases and the public-domain 《三國演義》
text from the desktop data folder, then builds the web novel library
(三國演義 only — 金庸 stays desktop-only) with bge-m3 embeddings from the
local Ollama. Upload the resulting web/data folder to the server.

Usage (from the web/ folder, with Ollama running):
  python scripts/prepare_data.py --desktop "C:/AI-Girlfriend/openmimicry-main/openmimicry-main" [--gpu]
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
DATA = WEB / "data"


async def build_novels(gpu: bool) -> None:
    from openmimicry.memory.semantic import OllamaEmbedder
    from openmimicry_backend.novels import NovelLibrary

    embedder = OllamaEmbedder(model="bge-m3", cpu_only=not gpu)
    library = NovelLibrary(DATA / "novels.sqlite", DATA / "novels_inbox", embedder,
                           terms_path=WEB / "config" / "novel_terms.yml")
    try:
        await library.import_inbox(progress=lambda message: print("  " + message, flush=True))
    finally:
        await embedder.close()
    for book in await library.books():
        print(f"  《{book.title}》 {book.chapters} 回 · 索引 {book.indexed}/{book.passages}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", required=True, help="desktop project folder (read only)")
    parser.add_argument("--gpu", action="store_true", help="embed on the GPU (faster)")
    args = parser.parse_args()
    desktop = Path(args.desktop) / "data"

    copies = {
        desktop / "bible" / "bible.sqlite": DATA / "bible.sqlite",
        desktop / "buddhist" / "buddhist.sqlite": DATA / "buddhist.sqlite",
        desktop / "novels" / "inbox" / "三國演義.txt": DATA / "novels_inbox" / "三國演義.txt",
    }
    for source, target in copies.items():
        if not source.is_file():
            print(f"missing (skipped): {source}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"copied {source.name} -> {target.relative_to(WEB)}")
    desktop_library = desktop / "novels" / "novels.sqlite"
    if desktop_library.is_file() and reuse_index(desktop_library):
        print("reused the desktop index for 三國演義 (金庸 and reading progress removed)")
    else:
        print("building the web novel library (三國演義)…")
        asyncio.run(build_novels(args.gpu))
    print(f"done: upload {DATA} to the server's web/data folder")


def reuse_index(desktop_library: Path) -> bool:
    """Copy the desktop library and keep only public-domain books (三國演義)."""

    import sqlite3

    target = DATA / "novels.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{desktop_library.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    with destination:
        source.backup(destination)  # consistent copy; the desktop file is not modified
    source.close()
    connection = destination
    connection.execute("PRAGMA foreign_keys=ON")
    keep = connection.execute("SELECT id FROM books WHERE title = '三國演義'").fetchone()
    if keep is None:
        connection.close()
        target.unlink()
        return False
    with connection:
        connection.execute("DELETE FROM books WHERE title <> '三國演義'")
        connection.execute("DELETE FROM progress")
    unindexed = connection.execute("SELECT COUNT(*) FROM passages WHERE vector IS NULL").fetchone()[0]
    connection.execute("VACUUM")
    for title, chapters, passages in connection.execute(
        "SELECT b.title, b.chapters, COUNT(p.id) FROM books b JOIN passages p ON p.book_id = b.id GROUP BY b.id"
    ):
        print(f"  《{title}》 {chapters} 回 · {passages} 段 · 未索引 {unindexed}")
    connection.close()
    return unindexed == 0


if __name__ == "__main__":
    main()

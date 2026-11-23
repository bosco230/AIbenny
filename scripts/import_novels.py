"""Import every book in data/novels/inbox into the shared 金庸小說 library.

Same code path as the backend's startup import (NovelLibrary.import_inbox),
but with progress output — useful for the first big import, which embeds
~18,000 passages with bge-m3 on the CPU (roughly 15-25 minutes).

Safe to stop and re-run: imported books are skipped (SHA-256) and only
passages without an embedding are indexed.

Usage:  python scripts/import_novels.py [--gpu]
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    from openmimicry.memory.semantic import OllamaEmbedder
    from openmimicry_backend.novels import NovelLibrary

    started = time.monotonic()

    def report(message: str) -> None:
        print(f"[{time.monotonic() - started:6.0f}s] {message}", flush=True)

    # --gpu: index on the GPU (much faster; use while Benny is not running,
    # so Whisper is not holding VRAM). Chat-time queries stay on the CPU.
    embedder = OllamaEmbedder(model="bge-m3", cpu_only="--gpu" not in sys.argv)
    library = NovelLibrary(ROOT / "data" / "novels" / "novels.sqlite", ROOT / "data" / "novels" / "inbox", embedder)
    try:
        await library.import_inbox(progress=report)
    finally:
        await embedder.close()
    for book in await library.books():
        report(f"《{book.title}》 {book.chapters} 回 · {book.characters // 1000}k 字 · 索引 {book.indexed}/{book.passages}")
    report("完成")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())

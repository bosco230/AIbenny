"""Download 《三國演義》 (120 回, public domain) from zh.wikisource as one TXT.

Uses the MediaWiki API (50 pages per request, 3 requests in total) and
writes data/novels/inbox/三國演義.txt with one 「第N回　回目」 heading per
chapter, ready for the shared novel library (NovelLibrary.import_inbox).

Wiki markup is removed: templates, bold quotes, links, refs, HTML tags.
Poem lines (wiki "::" indents) are kept as indented lines.

Usage:  python -I scripts/fetch_sanguo.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "novels" / "inbox" / "三國演義.txt"
API = "https://zh.wikisource.org/w/api.php"
USER_AGENT = "BennyCompanion/1.0 (personal reading library; low-rate)"
CHAPTERS = 120


def fetch(titles: list[str]) -> dict[str, str]:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(titles),
            "format": "json",
            "formatversion": "2",
        }
    )
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    pages = {}
    for page in data["query"]["pages"]:
        if "revisions" in page:
            pages[page["title"]] = page["revisions"][0]["slots"]["main"]["content"]
    return pages


def heading(wikitext: str, number: int) -> str:
    match = re.search(r"\{\{Novel\|[^|]*\|([^|}]+)", wikitext)
    title = match.group(1) if match else f"第{number}回"
    title = re.sub(r"'''?", "", title).strip()
    return title if title.startswith("第") else f"第{number}回　{title}"


def clean(wikitext: str) -> str:
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", wikitext, flags=re.S)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)  # templates (incl. navigation)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)  # [[a|b]] -> b
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith(":"):
            line = "　　　　" + line.lstrip(":").strip()
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    titles = [f"三國演義/第{n:03d}回" for n in range(1, CHAPTERS + 1)]
    pages: dict[str, str] = {}
    for start in range(0, len(titles), 50):
        pages.update(fetch(titles[start : start + 50]))
        print(f"fetched {len(pages)}/{len(titles)}", flush=True)
        time.sleep(1.0)
    missing = [t for t in titles if t not in pages]
    if missing:
        raise SystemExit(f"missing pages: {missing}")
    parts = ["三國演義", "羅貫中（毛宗崗評本）·來源：維基文庫（公有領域）", ""]
    for number, title in enumerate(titles, start=1):
        wikitext = pages[title]
        parts.append(heading(wikitext, number))
        parts.append("")
        parts.append(clean(wikitext))
        parts.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {CHAPTERS} 回)")


if __name__ == "__main__":
    main()

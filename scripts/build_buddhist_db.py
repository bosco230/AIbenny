"""Build data/buddhist/buddhist.sqlite from CBETA TEI XML (Taishō canon).

Sources (CBETA, CC BY-NC-SA, personal non-commercial use), downloaded from
https://github.com/cbeta-org/xml-p5 into data/buddhist/sources/:

  T08n0251  般若波羅蜜多心經（玄奘譯）
  T08n0235  金剛般若波羅蜜經（鳩摩羅什譯）
  T12n0366  佛說阿彌陀經（鳩摩羅什譯）
  T09n0262  妙法蓮華經 — only 第二十五 觀世音菩薩普門品（鳩摩羅什譯）

Imperial prefaces, appendices, editorial notes and variant readings are
skipped; rare characters (<g>) are resolved through the file's charDecl.

Usage:  python -I scripts/build_buddhist_db.py [sources_dir] [output.sqlite]
"""

from __future__ import annotations

import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

TEI = "{http://www.tei-c.org/ns/1.0}"
CB = "{http://www.cbeta.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@dataclass(frozen=True)
class Sutra:
    code: str
    name: str
    short: str
    aliases: tuple[str, ...]
    translator: str
    only_pin: str | None = None  # keep just this 品 (by mulu n)


SUTRAS = (
    Sutra("T08n0251", "般若波羅蜜多心經", "心經", ("心經", "般若心經", "多心經", "波羅蜜多心經"), "唐 玄奘譯"),
    Sutra("T08n0235", "金剛般若波羅蜜經", "金剛經", ("金剛經", "金剛般若經", "金剛般若波羅蜜經"), "姚秦 鳩摩羅什譯"),
    Sutra("T12n0366", "佛說阿彌陀經", "阿彌陀經", ("阿彌陀經", "彌陀經", "佛說阿彌陀經"), "姚秦 鳩摩羅什譯"),
    Sutra(
        "T09n0262",
        "妙法蓮華經觀世音菩薩普門品",
        "普門品",
        ("普門品", "觀世音菩薩普門品", "觀音經", "法華經普門品"),
        "姚秦 鳩摩羅什譯",
        only_pin="25",
    ),
)

# Elements whose text is never scripture.
SKIP = {
    f"{TEI}note", f"{TEI}rdg", f"{CB}mulu", f"{CB}docNumber", f"{TEI}byline",
    f"{TEI}head", f"{CB}jhead", f"{CB}juan", f"{TEI}teiHeader", f"{CB}sg",
}
SKIP_DIV_TYPES = {"xu", "序", "附文", "w", "fu-wen"}
SKIP_MULU_TYPES = {"序", "附文"}


def char_map(root: ET.Element) -> dict[str, str]:
    """Map gaiji ids (#CBxxxxx) to a Unicode character or normalized form."""

    mapping: dict[str, str] = {}
    for char in root.iter(f"{TEI}char"):
        cid = char.get(XML_ID)
        if not cid:
            continue
        chosen = None
        for m in char.iter(f"{TEI}mapping"):
            if m.get("type") in ("unicode", "normal_unicode") and m.text:
                code = m.text.strip().removeprefix("U+")
                try:
                    chosen = chr(int(code, 16))
                    break
                except ValueError:
                    pass
        if chosen is None:
            for prop in char.iter(f"{TEI}charProp"):
                name = prop.findtext(f"{TEI}localName") or ""
                if name in ("normalized form", "Character in the Siddham font") and prop.findtext(f"{TEI}value"):
                    chosen = prop.findtext(f"{TEI}value")
                    break
        mapping["#" + cid] = chosen or "□"
    return mapping


def text_of(element: ET.Element, gaiji: dict[str, str]) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag in SKIP:
            if node.tail:
                parts.append(node.tail)
            return
        if node.tag == f"{TEI}g":
            parts.append(gaiji.get(node.get("ref", ""), node.text or "□"))
        else:
            if node.text:
                parts.append(node.text)
            for child in node:
                walk(child)
        if node.tail and node is not element:
            parts.append(node.tail)

    walk(element)
    return re.sub(r"\s+", "", "".join(parts))


def div_label(div: ET.Element) -> tuple[str | None, str | None, str | None]:
    mulu = div.find(f"{CB}mulu")
    if mulu is None:
        return None, None, None
    return mulu.get("type"), mulu.get("n"), (mulu.text or "").strip()


def passages(path: Path, sutra: Sutra) -> list[tuple[str, str]]:
    root = ET.parse(path).getroot()
    gaiji = char_map(root)
    body = root.find(f"{TEI}text/{TEI}body")
    out: list[tuple[str, str]] = []

    def walk(node: ET.Element, section: str, keep: bool) -> None:
        for child in node:
            if child.tag == f"{CB}div":
                mtype, mn, mtitle = div_label(child)
                if child.get("type") in SKIP_DIV_TYPES or mtype in SKIP_MULU_TYPES:
                    continue
                child_keep = keep
                child_section = section
                if mtype == "品":
                    child_section = re.sub(r"^\d+\s*", "", mtitle or section)
                    if sutra.only_pin is not None:
                        child_keep = mn == sutra.only_pin
                walk(child, child_section, child_keep)
            elif child.tag in (f"{TEI}p", f"{TEI}lg"):
                if keep:
                    text = text_of(child, gaiji)
                    if text:
                        out.append((section, text))
            elif child.tag not in SKIP:
                walk(child, section, keep)

    walk(body, "", sutra.only_pin is None)
    return out


def build(sources: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        CREATE TABLE sutras (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, short TEXT NOT NULL,
            aliases TEXT NOT NULL, translator TEXT NOT NULL, source TEXT NOT NULL
        );
        CREATE TABLE passages (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL REFERENCES sutras(code),
            seq INTEGER NOT NULL, section TEXT NOT NULL, text TEXT NOT NULL
        );
        CREATE INDEX idx_passages_code ON passages(code, seq);
        """
    )
    for sutra in SUTRAS:
        path = sources / f"{sutra.code}.xml"
        rows = passages(path, sutra)
        db.execute(
            "INSERT INTO sutras VALUES (?, ?, ?, ?, ?, ?)",
            (sutra.code, sutra.name, sutra.short, "|".join(sutra.aliases), sutra.translator,
             f"CBETA {sutra.code} (大正新脩大藏經)"),
        )
        db.executemany(
            "INSERT INTO passages(code, seq, section, text) VALUES (?, ?, ?, ?)",
            [(sutra.code, i + 1, section, text) for i, (section, text) in enumerate(rows)],
        )
        chars = sum(len(t) for _, t in rows)
        print(f"{sutra.short}: {len(rows)} passages, {chars} characters")
    db.commit()
    db.close()
    tmp.replace(output)


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1]
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "data" / "buddhist" / "sources"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "data" / "buddhist" / "buddhist.sqlite"
    sys.stdout.reconfigure(encoding="utf-8")
    build(src, dst)

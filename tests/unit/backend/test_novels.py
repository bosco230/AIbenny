"""Finance-novel library: import, chapters, retrieval, spoiler guard, progress."""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from openmimicry_backend.novels import (  # noqa: E402
    NovelLibrary,
    chapter_number,
    chinese_number,
    extract_book,
    split_passages,
)

# An original short story written for these tests.
STORY = """海港風雲

第一章 開市
阿明係中環一間細行嘅交易員，每朝七點就返到公司睇期指。
佢老細陳生成日話：「炒賣最緊要識止蝕。」

第二章 槓桿
阿明見恒指升咗一個月，就用十倍槓桿買入期指，諗住賺快錢。
同事阿玲提醒佢，槓桿可以放大利潤，亦可以放大損失。

第三章 沽空
一間地產股公布業績差過預期，阿玲決定沽空，即係借股票嚟賣，等跌咗再買返還。
阿明覺得沽空好危險，因為股價理論上可以無限咁升。

第四章 爆倉
恒指突然急跌，阿明收到追加保證金通知，最後被斬倉，輸晒積蓄。
陳生拍拍佢膊頭：「市場永遠都喺度，最緊要人仲喺度。」
"""


class _KeywordEmbedder:
    model = "fake"
    words = ("槓桿", "沽空", "爆倉", "斬倉", "止蝕", "交易員", "阿明", "阿玲", "保證金")

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[1.0 if w in t else 0.0 for w in self.words] + [0.05] for t in texts]


def _write_inputs(inbox: Path) -> None:
    inbox.mkdir(parents=True)
    (inbox / "海港風雲.txt").write_bytes(STORY.encode("big5hkscs"))


def _epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>《銀行家》</dc:title>'
            "<dc:creator>測試作者</dc:creator></metadata><manifest>"
            '<item id="c1" href="c1.xhtml"/><item id="c2" href="c2.xhtml"/></manifest>'
            '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>',
        )
        body = "<p>" + "銀行家講利率同債券。" * 10 + "</p>"
        z.writestr("OEBPS/c1.xhtml", f"<html><body><h1>第一章 利率</h1>{body}</body></html>")
        z.writestr("OEBPS/c2.xhtml", f"<html><body><h1>第二章 擠提</h1>{body}擠提</body></html>")


def test_chinese_numbers() -> None:
    assert chinese_number("12") == 12
    assert chinese_number("十二") == 12
    assert chinese_number("一百零三") == 103
    assert chinese_number("兩") == 2


def test_txt_big5_chapters_and_epub(tmp_path: Path) -> None:
    _write_inputs(tmp_path / "in")
    book = extract_book(tmp_path / "in" / "海港風雲.txt")
    assert [title for title, _ in book.chapters] == ["第一章 開市", "第二章 槓桿", "第三章 沽空", "第四章 爆倉"]
    assert "止蝕" in book.chapters[0][1]

    _epub(tmp_path / "bank.epub")
    epub = extract_book(tmp_path / "bank.epub")
    assert epub.title == "《銀行家》" and epub.author == "測試作者"
    assert [t for t, _ in epub.chapters] == ["第一章 利率", "第二章 擠提"]


def test_split_passages_respects_size() -> None:
    passages = split_passages("句子。" * 400, target=100, maximum=150)
    assert all(len(p) <= 150 for p in passages)
    assert "".join(passages).replace("\n", "") == "句子。" * 400


def test_import_retrieve_progress_and_spoiler_guard(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _write_inputs(inbox)
    library = NovelLibrary(tmp_path / "novels.sqlite", inbox, _KeywordEmbedder(), threshold=0.3)

    async def scenario():  # type: ignore[no-untyped-def]
        first = await library.import_inbox()
        again = await library.import_inbox()
        books = await library.books()
        plain = await library.context("今日天氣好好")
        leverage = await library.context("《海港風雲》入面阿明點樣用槓桿？")
        progress_note = await library.context("我睇到《海港風雲》第二章")
        spoiler = await library.context("《海港風雲》阿明最後有冇被斬倉？")
        ok_spoiler = await library.context("《海港風雲》阿明最後有冇被斬倉？我睇完喇，劇透都得")
        library_list = await library.context("有咩書推介？")
        return first, again, books, plain, leverage, progress_note, spoiler, ok_spoiler, library_list

    first, again, books, plain, leverage, progress_note, spoiler, ok_spoiler, library_list = asyncio.run(scenario())
    assert first[0]["status"] == "imported" and first[0]["chapters"] == 4
    assert again[0]["status"] == "already imported"
    assert books[0].indexed == books[0].passages > 0
    assert plain is None  # ordinary chat never pulls in novels
    assert leverage is not None and "十倍槓桿" in leverage and "第二章 槓桿" in leverage
    assert progress_note is not None and "第二章 槓桿" in progress_note
    assert spoiler is not None and "斬倉" not in spoiler and "防劇透" in spoiler
    assert ok_spoiler is not None and "斬倉" in ok_spoiler
    assert library_list is not None and "《海港風雲》" in library_list and "讀到 第二章 槓桿" in library_list


# ------------------------------------------------------------ Haodoo .updb


def _updb(path: Path, title: str, records: list[str]) -> None:
    """Write a minimal Haodoo .updb: Palm DB, type BOOK, creator MTIU, UTF-16LE."""

    payloads = [b" " * 8 + title.encode("utf-16-le") + b"\x1b\x00\x1b\x00\x1b\x00"]
    payloads += [text.encode("utf-16-le") for text in records]
    payloads.append(b"\xff\xff")
    header = bytearray(78)
    header[0:4] = b"test"
    header[60:68] = b"BOOKMTIU"
    header[76:78] = len(payloads).to_bytes(2, "big")
    offset = 78 + 8 * len(payloads) + 2
    table = bytearray()
    for payload in payloads:
        table += offset.to_bytes(4, "big") + bytes(4)
        offset += len(payload)
    path.write_bytes(bytes(header) + bytes(table) + b"\x00\x00" + b"".join(payloads))


HEADER = "︽江湖夜雨一︾金庸\r\n︽二○一六年五月六日版︾\r\n︽好讀書櫃︾典藏版\r\n\r\n\r\n"


def _write_updb_volumes(inbox: Path) -> None:
    inbox.mkdir(parents=True)
    _updb(inbox / "江湖夜雨1.updb", "江湖夜雨一", [
        HEADER + "序\r\n\r\n　　呢個係序言，講下寫書嘅緣起。",
        "第一回　雨夜\r\n\r\n　　喬大俠話：﹁今晚雨大，唔好出門。﹂佢練緊降龍掌。",
        "　　※※※\r\n\r\n　　雨停之後，佢見到︽武林秘笈︾放喺枱面。",
    ])
    _updb(inbox / "江湖夜雨二.updb", "江湖夜雨二", [
        HEADER.replace("一", "二", 1) + "第二回　決戰\r\n\r\n　　少林寺前，喬大俠以降龍掌迎戰群雄。",
        "第三回　歸隱\r\n\r\n　　最後喬大俠斬斷恩怨，歸隱雁門。",
    ])


class _WuxiaEmbedder:
    model = "fake"
    words = ("喬大俠", "降龍掌", "雨", "秘笈", "少林", "歸隱", "雁門", "序")

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[1.0 if w in t else 0.0 for w in self.words] + [0.05] for t in texts]


def test_updb_parsing_punctuation_and_continuation(tmp_path: Path) -> None:
    _write_updb_volumes(tmp_path / "in")
    book = extract_book(tmp_path / "in" / "江湖夜雨1.updb")
    assert book.title == "江湖夜雨一" and book.author == "金庸"
    assert [t for t, _ in book.chapters] == ["序", "第一回　雨夜"]
    body = book.chapters[1][1]
    assert "「今晚雨大，唔好出門。」" in body  # vertical quotes converted
    assert "《武林秘笈》" in body  # ※※※ continuation joined to 第一回
    assert "好讀書櫃" not in book.chapters[0][1]


def test_chapter_numbers() -> None:
    assert chapter_number("第四一回　漁陽鼓動天方醉") == 41
    assert chapter_number("十六回　昔時因") == 16
    assert chapter_number("一　玄鐵令") == 1
    assert chapter_number("後記") is None
    assert chinese_number("二○") == 20


def test_updb_volumes_merge_and_progress_maps_to_titled_chapter(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _write_updb_volumes(inbox)
    library = NovelLibrary(tmp_path / "n.sqlite", inbox, _WuxiaEmbedder(), threshold=0.3)

    async def scenario():  # type: ignore[no-untyped-def]
        results = await library.import_inbox()
        note = await library.context("我睇到江湖夜雨第一回，好好睇")  # no 《》 needed
        books = await library.books()
        guarded = await library.context("《江湖夜雨》喬大俠最後有冇歸隱雁門？")
        strong = await library.context("喬大俠嘅降龍掌")  # no book words, strong match
        weak = await library.context("今晚落雨")  # weak match, ordinary chat
        return results, books, note, guarded, strong, weak

    results, books, note, guarded, strong, weak = asyncio.run(scenario())
    assert len(results) == 1 and results[0]["title"] == "江湖夜雨"
    assert results[0]["chapters"] == 4  # 序 + 第一回 + 第二回 + 第三回, one merged book
    assert books[0].title == "江湖夜雨"
    # 第一回 is the 2nd chapter because of the 序 before it.
    assert books[0].progress == 2 and note is not None and "第一回" in note
    assert guarded is not None and "歸隱雁門。" not in guarded and "防劇透" in guarded
    assert strong is not None and "降龍掌" in strong
    assert weak is None


def test_delete_book(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _write_inputs(inbox)
    library = NovelLibrary(tmp_path / "novels.sqlite", inbox, None)

    async def scenario():  # type: ignore[no-untyped-def]
        await library.import_inbox()
        book = (await library.books())[0]
        return await library.delete(book.id), await library.books()

    deleted, remaining = asyncio.run(scenario())
    assert deleted and remaining == []


def test_lexicon_and_episode_routing(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _write_updb_volumes(inbox)
    terms = tmp_path / "terms.yml"
    terms.write_text(
        "江湖夜雨: [喬大俠, 降龍掌]\n海港風雲: [阿明]\n_episodes:\n  江湖夜雨:\n    少林決戰: 2\n",
        encoding="utf-8",
    )
    library = NovelLibrary(tmp_path / "n.sqlite", inbox, _WuxiaEmbedder(), threshold=0.99, terms_path=terms)

    async def scenario():  # type: ignore[no-untyped-def]
        await library.import_inbox()
        episode = await library.context("少林決戰係點？")  # no title: lexicon + episode
        plain = await library.context("今日好攰")
        await library.context("我睇到江湖夜雨第一回")
        guarded = await library.context("少林決戰係點？")  # episode is past progress
        return episode, plain, guarded

    episode, plain, guarded = asyncio.run(scenario())
    assert episode is not None and "第二回\u3000決戰" in episode and "少林寺前" in episode
    assert plain is None
    assert guarded is None or "少林寺前" not in guarded

from __future__ import annotations

from pathlib import Path

import pytest

from openmimicry.voice.tts.qwen3 import Qwen3TTSAdapter


async def test_sentence_stream_splits_chinese_sentences() -> None:
    adapter = Qwen3TTSAdapter()
    text = "你好。今日天氣很好！你食咗飯未？我哋開始測試。"

    chunks = [
        chunk async for chunk in adapter._sentence_stream(text)
    ]

    assert chunks == [
        "你好。",
        "今日天氣很好！",
        "你食咗飯未？",
        "我哋開始測試。",
    ]


async def test_sentence_stream_handles_split_input_chunks() -> None:
    adapter = Qwen3TTSAdapter()

    async def source():
        yield "你好"
        yield "。今日天氣"
        yield "很好！"
        yield "測試完成"

    chunks = [
        chunk async for chunk in adapter._sentence_stream(source())
    ]

    assert chunks == [
        "你好。",
        "今日天氣很好！",
        "測試完成",
    ]


async def test_sentence_stream_splits_long_text() -> None:
    adapter = Qwen3TTSAdapter()
    text = "A" * 120

    chunks = [
        chunk async for chunk in adapter._sentence_stream(text)
    ]

    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= 55 for chunk in chunks)


async def test_sentence_stream_preserves_final_text_without_punctuation() -> None:
    adapter = Qwen3TTSAdapter()

    async def source():
        yield "第一句。"
        yield "最後一句沒有標點"

    chunks = [
        chunk async for chunk in adapter._sentence_stream(source())
    ]

    assert chunks == [
        "第一句。",
        "最後一句沒有標點",
    ]


async def test_remove_file_deletes_temp_file_and_tracking_entry(
    tmp_path: Path,
) -> None:
    adapter = Qwen3TTSAdapter()
    wave_path = tmp_path / "test.wav"
    wave_path.write_bytes(b"test audio")

    adapter._active_files.add(str(wave_path))
    adapter._remove_file(str(wave_path))

    assert not wave_path.exists()
    assert str(wave_path) not in adapter._active_files


async def test_wait_until_ready_returns_false_before_speaking() -> None:
    adapter = Qwen3TTSAdapter()

    assert await adapter.wait_until_ready(timeout_s=0.05) is False


async def test_wait_until_ready_returns_resolved_value() -> None:
    adapter = Qwen3TTSAdapter()
    adapter._ready_future = __import__("asyncio").get_running_loop().create_future()

    adapter._resolve_ready(True)

    assert await adapter.wait_until_ready(timeout_s=0.1) is True


async def test_synthesis_worker_recovers_after_request_error() -> None:
    import asyncio
    import json

    class FakeInput:
        def __init__(self):
            self.payloads = []

        def write(self, payload: bytes) -> None:
            self.payloads.append(payload)

        async def drain(self) -> None:
            pass

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stdin = FakeInput()
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(
                b'{"type":"error","message":"temporary synthesis error"}\n'
                b'{"type":"complete"}\n'
            )

    adapter = Qwen3TTSAdapter()
    process = FakeProcess()
    adapter._process = process

    with pytest.raises(RuntimeError, match="temporary synthesis error"):
        await adapter._synthesize("第一句", "first.wav")

    assert adapter._process is process

    await adapter._synthesize("第二句", "second.wav")

    assert adapter._process is process
    assert len(process.stdin.payloads) == 2

    first_request = json.loads(process.stdin.payloads[0].decode("utf-8"))
    second_request = json.loads(process.stdin.payloads[1].decode("utf-8"))

    assert first_request["text"] == "第一句"
    assert second_request["text"] == "第二句"

async def test_first_audio_starts_before_text_stream_finishes(
    monkeypatch,
) -> None:
    import asyncio

    import openmimicry.voice.tts.qwen3 as qwen3_module

    playback_started = asyncio.Event()
    allow_source_to_finish = asyncio.Event()
    playback_finished = asyncio.Event()
    source_finished = asyncio.Event()

    class FakePlayback:
        returncode = None

        async def wait(self):
            await playback_finished.wait()
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = 0

    async def fake_synthesize(text, output_path):
        Path(output_path).write_bytes(b"fake wav")

    async def fake_create_subprocess_exec(*args, **kwargs):
        playback_started.set()
        return FakePlayback()

    def fake_playback_command(path):
        return ["fake-player"], None

    monkeypatch.setattr(
        qwen3_module.Qwen3TTSAdapter,
        "_synthesize",
        staticmethod(fake_synthesize),
    )
    monkeypatch.setattr(
        qwen3_module,
        "_playback_command",
        fake_playback_command,
    )
    monkeypatch.setattr(
        qwen3_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    async def text_source():
        yield "\u7b2c\u4e00\u53e5\u3002"
        await allow_source_to_finish.wait()
        source_finished.set()

    adapter = Qwen3TTSAdapter()
    speech_task = asyncio.create_task(
        adapter.speak(text_source(), config=None)
    )

    try:
        await asyncio.wait_for(playback_started.wait(), timeout=3)

        assert not source_finished.is_set()
        assert adapter.is_speaking is True

    finally:
        allow_source_to_finish.set()
        playback_finished.set()
        await asyncio.wait_for(speech_task, timeout=3)

    assert adapter.is_speaking is False
    assert not adapter._active_files

async def test_cancellation_stops_playback_and_cleans_up(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import asyncio

    import openmimicry.voice.tts.qwen3 as qwen3_module

    playback_started = asyncio.Event()
    source_cancelled = asyncio.Event()
    created_files: list[str] = []

    class FakePlayback:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.finished = asyncio.Event()

        async def wait(self):
            await self.finished.wait()
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            self.finished.set()

        def kill(self):
            self.returncode = -9
            self.finished.set()

    playback = FakePlayback()

    async def fake_synthesize(text, output_path):
        Path(output_path).write_bytes(b"fake wav")
        created_files.append(output_path)

    async def fake_create_subprocess_exec(*args, **kwargs):
        playback_started.set()
        return playback

    monkeypatch.setattr(
        qwen3_module.Qwen3TTSAdapter,
        "_synthesize",
        staticmethod(fake_synthesize),
    )
    monkeypatch.setattr(
        qwen3_module,
        "_playback_command",
        lambda path: (["fake-player"], None),
    )
    monkeypatch.setattr(
        qwen3_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    async def text_source():
        try:
            yield "\u7b2c\u4e00\u53e5\u3002"
            await asyncio.Event().wait()
        finally:
            source_cancelled.set()

    adapter = Qwen3TTSAdapter()
    speech_task = asyncio.create_task(
        adapter.speak(text_source(), config=None)
    )

    try:
        await asyncio.wait_for(playback_started.wait(), timeout=3)

        assert adapter.is_speaking is True
        assert len(created_files) == 1
        assert Path(created_files[0]).exists()

        speech_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(speech_task, timeout=3)

    finally:
        if not speech_task.done():
            speech_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(speech_task, timeout=3)

    assert playback.terminated is True
    assert source_cancelled.is_set()
    assert adapter.is_speaking is False
    assert not adapter._active_files
    assert all(not Path(path).exists() for path in created_files)

async def test_sentence_stream_splits_at_comma_after_minimum_length() -> None:
    adapter = Qwen3TTSAdapter()
    text = (
        "\u5514\u8a72\u5566\uff0c"
        "\u6211\u4eca\u65e5\u4fc2\u96fb\u8166\u88e1\u5ea6\u904e\u5566\uff0c"
        "\u4e0d\u904e\u90fd\u5514\u932f\u5566\uff01"
    )

    chunks = [
        chunk async for chunk in adapter._sentence_stream(text)
    ]

    assert chunks == [
        "\u5514\u8a72\u5566\uff0c"
        "\u6211\u4eca\u65e5\u4fc2\u96fb\u8166\u88e1\u5ea6\u904e\u5566\uff0c",
        "\u4e0d\u904e\u90fd\u5514\u932f\u5566\uff01",
    ]


async def test_sentence_stream_does_not_split_at_short_comma() -> None:
    adapter = Qwen3TTSAdapter()
    text = "\u4f60\u597d\uff0c\u4eca\u5929\u5f88\u597d\uff01"

    chunks = [
        chunk async for chunk in adapter._sentence_stream(text)
    ]

    assert chunks == [text]

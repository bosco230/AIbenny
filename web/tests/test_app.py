"""Web edition: login, isolation between visitors, limits, voice, static files."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benny_web.app import create_app
from benny_web.brain import Brain
from benny_web.settings import REPO_ROOT, Settings
from benny_web.voice import mouth_frames

PASSCODE = "secret-pass"


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []  # character replies only

    async def chat(self, messages, *, model, json_mode=False, temperature=0.6, max_tokens=600):  # type: ignore[no-untyped-def]
        if json_mode:
            self.calls.append(messages)
            last = messages[-1]["content"]
            return json.dumps({"reply": f"收到：{last}", "emotion": "happy", "intensity": 0.8})
        return '{"memories": []}'

    async def close(self) -> None:
        return None


class FakeEmbedder:
    model = "fake"

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def close(self) -> None:
        return None


class FakeSpeech:
    available = True

    async def synthesize(self, text, voice):  # type: ignore[no-untyped-def]
        return {"audio": "data:audio/wav;base64,AAAA", "frames": [0, 1, 2], "window_ms": 40, "voice": voice}

    async def transcribe(self, wav):  # type: ignore[no-untyped-def]
        return "你好呀"

    async def close(self) -> None:
        return None


def make_client(tmp_path: Path, **limits: int) -> tuple[TestClient, FakeLLM]:
    base = Settings.from_env()
    settings = replace(
        base,
        passcode=PASSCODE,
        session_secret="x" * 40,
        secure_cookies=False,
        openrouter_key="test",
        data_dir=tmp_path,
        characters_dir=REPO_ROOT / "characters",
        **limits,
    )
    llm = FakeLLM()
    brain = Brain(settings, llm, embedder=FakeEmbedder())  # type: ignore[arg-type]
    app = create_app(settings, brain=brain, speech=FakeSpeech())  # type: ignore[arg-type]
    return TestClient(app), llm


def login(client: TestClient) -> None:
    assert client.post("/api/login", json={"passcode": PASSCODE}).status_code == 200


def test_requires_passcode_and_throttles_guessing(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 401
    for _ in range(5):
        assert client.post("/api/login", json={"passcode": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"passcode": PASSCODE}).status_code == 429


def test_login_chat_and_forged_cookie(tmp_path: Path) -> None:
    client, llm = make_client(tmp_path)
    login(client)
    assert client.get("/api/me").json()["voice"] is True
    reply = client.post("/api/chat", json={"text": "你好", "character": "dingdong"}).json()
    assert reply == {"character": "dingdong", "reply": "收到：你好", "emotion": "happy", "intensity": 0.8}
    # The web persona and shared rules are sent; no 金庸 in the web rules.
    system = "\n".join(m["content"] for m in llm.calls[-1] if m["role"] == "system")
    assert "黃輝" in system and "網頁" in system and "金庸" not in system

    forger = TestClient(client.app, cookies={"benny_session": "0" * 32 + ".9999999999.deadbeef"})
    assert forger.get("/api/me").status_code == 401


def test_visitors_do_not_see_each_other(tmp_path: Path) -> None:
    alice, llm = make_client(tmp_path)
    login(alice)
    alice.post("/api/chat", json={"text": "我叫阿麗，住喺沙田"})
    bob = TestClient(alice.app)
    login(bob)
    bob.post("/api/chat", json={"text": "你記唔記得我？"})
    bob_messages = "\n".join(m["content"] for m in llm.calls[-1])
    assert "阿麗" not in bob_messages
    # Alice's own history carries over to her next turn.
    alice.post("/api/chat", json={"text": "我住邊？"})
    assert any("阿麗" in m["content"] for m in llm.calls[-1])


def test_message_limit(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, messages_per_10min=2)
    login(client)
    assert client.post("/api/chat", json={"text": "一"}).status_code == 200
    assert client.post("/api/chat", json={"text": "二"}).status_code == 200
    blocked = client.post("/api/chat", json={"text": "三"})
    assert blocked.status_code == 429 and "休息" in blocked.json()["detail"]


def test_voice_uses_character_voice_and_limits(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, tts_chars_per_day=10)
    login(client)
    spoken = client.post("/api/speak", json={"text": "你好呀", "character": "dingdong"}).json()
    assert spoken["voice"] == "zh-HK-WanLungNeural" and spoken["frames"] == [0, 1, 2]
    assert client.post("/api/speak", json={"text": "好長好長嘅一句說話呀"}).status_code == 429
    heard = client.post("/api/listen", content=b"RIFF....", headers={"Content-Type": "audio/wav"})
    assert heard.json() == {"text": "你好呀"}


def test_pages_and_only_avatar_folders_are_public(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert "AI 袁枝" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/avatar/benny/idle/000.png").status_code == 200
    assert client.get("/avatar/dingdong/happy/002.svg").status_code == 200
    assert client.get("/avatar/benny/../../config/user.yaml").status_code == 404


def test_forget_clears_history(tmp_path: Path) -> None:
    client, llm = make_client(tmp_path)
    login(client)
    client.post("/api/chat", json={"text": "記住我鍾意奶茶"})
    assert client.post("/api/forget").json() == {"ok": True}
    client.post("/api/chat", json={"text": "你記得咩？"})
    assert not any("奶茶" in m["content"] for m in llm.calls[-1] if m["role"] != "system")


def test_mouth_frames() -> None:
    import numpy as np

    loud = (np.sin(np.linspace(0, 400, 1600)) * 20000).astype("<i2").tobytes()
    frames = mouth_frames(b"\x00\x00" * 1600 + loud)
    assert frames[0] == 0 and max(frames) == 3

"""Benny ⇄ 叮當 switching through /characters/next."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openmimicry_backend.character_switch import CharacterSwitchBusyError
from openmimicry_backend.routes.characters import router


class _Switch:
    def __init__(self, busy: bool = False) -> None:
        self.active_id = "benny"
        self.busy = busy

    async def switch(self, character_id: str) -> str:
        if self.busy:
            raise CharacterSwitchBusyError("turn active")
        self.active_id = character_id
        return character_id


class _TTS:
    voice = "zh-HK-HiuMaanNeural"

    def set_voice(self, voice: str) -> None:
        self.voice = voice


class _Speech:
    def __init__(self) -> None:
        self.interrupted = 0
        self.said: list[str] = []

    async def interrupt(self) -> None:
        self.interrupted += 1

    async def say(self, text: str) -> str:
        self.said.append(text)
        return "u1"


class _Bridge:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, message: dict) -> None:
        self.published.append(message)


def _app(busy: bool = False) -> tuple[FastAPI, SimpleNamespace]:
    app = FastAPI()
    app.include_router(router)
    state = SimpleNamespace(
        tts=_TTS(), speech=_Speech(), bridge=_Bridge(), switch=_Switch(busy)
    )
    app.state.character_switch = state.switch
    app.state.wiring = SimpleNamespace(tts=state.tts, speech=state.speech)
    app.state.bridge = state.bridge
    app.state.mode_state = {"agent_voice": True}
    return app, state


def test_next_cycles_characters_switches_voice_and_greets() -> None:
    app, state = _app()
    with TestClient(app) as client:
        first = client.post("/characters/next").json()
        assert first["active"] == "dingdong" and first["changed"] is True
        assert state.tts.voice == "zh-HK-WanLungNeural"  # 叮當 uses a male voice
        assert state.bridge.published[-1]["type"] == "character.active"
        assert state.bridge.published[-1]["sprite_directory"] == "dingdong"
        assert state.speech.interrupted == 1

        second = client.post("/characters/next").json()
        assert second["active"] == "benny"
        assert state.tts.voice == "zh-HK-HiuMaanNeural"

        listing = client.get("/characters").json()
        assert listing["active"] == "benny"
        assert [c["id"] for c in listing["characters"]] == ["benny", "dingdong"]
    asyncio.run(asyncio.sleep(0))
    assert any("叮當" in text for text in state.speech.said)


def test_busy_switch_returns_409_and_keeps_voice() -> None:
    app, state = _app(busy=True)
    with TestClient(app) as client:
        response = client.post("/characters/next")
    assert response.status_code == 409
    assert state.tts.voice == "zh-HK-HiuMaanNeural"
    assert state.bridge.published == []


def test_unknown_character_is_404() -> None:
    app, _ = _app()
    with TestClient(app) as client:
        assert client.post("/characters/nobody/select").status_code == 404

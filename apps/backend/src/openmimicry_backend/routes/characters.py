"""Switch the active companion (Benny ⇄ 叮當).

Switching swaps the short-term conversation history, the personality prompt
(used by the chat turn via ``character_memories.active_id``), the Azure voice
and the avatar shown by the frontend (``character.active`` broadcast).
Long-term memory about the user is shared by both characters.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request

from ..character_switch import CharacterSwitchBusyError
from ..characters import CHARACTERS, CharacterProfile, get_character

__all__ = ["character_message", "router"]

router = APIRouter()
_log = logging.getLogger(__name__)


def character_message(profile: CharacterProfile) -> dict[str, Any]:
    return {
        "type": "character.active",
        "id": profile.character_id,
        "display_name": profile.display_name,
        "sprite_directory": profile.sprite_directory,
        "voice": profile.azure_voice,
    }


def _order() -> list[str]:
    return list(CHARACTERS)


@router.get("/characters")
async def list_characters(request: Request) -> dict[str, object]:
    active = request.app.state.character_switch.active_id
    return {
        "active": active,
        "characters": [
            {
                "id": profile.character_id,
                "display_name": profile.display_name,
                "voice": profile.azure_voice,
                "sprite_directory": profile.sprite_directory,
            }
            for profile in CHARACTERS.values()
        ],
    }


async def _switch(request: Request, character_id: str) -> dict[str, object]:
    try:
        profile = get_character(character_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    state = request.app.state
    switch = state.character_switch
    if switch.active_id == profile.character_id:
        return {"active": profile.character_id, "changed": False, **character_message(profile)}

    # Stop the current character mid-sentence so the switch is immediate.
    try:
        await state.wiring.speech.interrupt()
    except Exception:  # pragma: no cover - interrupt is best effort
        _log.warning("CHARACTER_SWITCH: speech interrupt failed", exc_info=True)
    try:
        await switch.switch(profile.character_id)
    except CharacterSwitchBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    set_voice = getattr(state.wiring.tts, "set_voice", None)
    if callable(set_voice):
        set_voice(profile.azure_voice)
    message = character_message(profile)
    await state.bridge.publish(message)
    _log.info("CHARACTER_SWITCHED: %s voice=%s", profile.character_id, profile.azure_voice)

    # The new companion greets in their own voice, confirming the switch.
    greeting = _greeting(profile)
    if greeting and state.mode_state.get("agent_voice", True):
        task = asyncio.create_task(_say(state.wiring.speech, greeting))
        _GREETINGS.add(task)
        task.add_done_callback(_GREETINGS.discard)
    return {"active": profile.character_id, "changed": True, "greeting": greeting, **message}


_GREETINGS: set[asyncio.Task[None]] = set()


def _greeting(profile: CharacterProfile) -> str | None:
    try:
        data = yaml.safe_load(Path(profile.personality_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    greeting = data.get("greeting") if isinstance(data, dict) else None
    return greeting.strip() if isinstance(greeting, str) and greeting.strip() else None


async def _say(speech: Any, text: str) -> None:
    try:
        await speech.say(text)
    except Exception:
        _log.warning("CHARACTER_SWITCH: greeting failed", exc_info=True)


@router.post("/characters/next")
async def next_character(request: Request) -> dict[str, object]:
    order = _order()
    active = request.app.state.character_switch.active_id
    index = order.index(active) if active in order else -1
    return await _switch(request, order[(index + 1) % len(order)])


@router.post("/characters/{character_id}/select")
async def select_character(character_id: str, request: Request) -> dict[str, object]:
    return await _switch(request, character_id)

"""Benny and Ding Dong character definitions.

Configuration only. No runtime switching is performed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CharacterProfile:
    character_id: str
    display_name: str
    azure_voice: str
    personality_path: Path
    sprite_directory: str


CHARACTERS: dict[str, CharacterProfile] = {
    "benny": CharacterProfile(
        character_id="benny",
        display_name="Benny",
        azure_voice="zh-HK-HiuMaanNeural",
        personality_path=Path("config/personality.yml"),
        sprite_directory="ai_girlfriend",
    ),
    "dingdong": CharacterProfile(
        character_id="dingdong",
        display_name="\u53ee\u7576",
        azure_voice="zh-HK-WanLungNeural",
        personality_path=Path("config/personalities/dingdong.yml"),
        sprite_directory="dingdong",
    ),
}

DEFAULT_CHARACTER_ID = "benny"


def get_character(character_id: str) -> CharacterProfile:
    try:
        return CHARACTERS[character_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown character ID: {character_id!r}"
        ) from exc
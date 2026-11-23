"""Combine existing English and conservative Cantonese extraction."""

from .cantonese_extractor import CantoneseExtractor
from .extractors import DeterministicExtractor
from .models import MemoryCandidate


class BilingualExtractor:
    """Extract memory candidates using both language extractors."""

    def __init__(self) -> None:
        self.english = DeterministicExtractor()
        self.cantonese = CantoneseExtractor()

    def extract(
        self,
        user_text: str,
        assistant_text: str = "",
    ) -> list[MemoryCandidate]:
        if not isinstance(user_text, str):
            return []

        english_candidates = self.english.extract(
            user_text, assistant_text
        )
        cantonese_candidates = self.cantonese.extract(
            user_text, assistant_text
        )

        combined = []
        seen = set()

        for candidate in english_candidates + cantonese_candidates:
            key = (
                candidate.subject,
                candidate.predicate,
                candidate.value.casefold(),
            )

            if key in seen:
                continue

            seen.add(key)
            combined.append(candidate)

        return combined

"""Per-visitor and global usage limits (protects OpenRouter and Azure bills).

Daily counters are stored in data/usage.json so a restart does not reset
them; the 10-minute burst window is kept in memory.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path


class LimitExceeded(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Limits:
    def __init__(self, path: Path, *, messages_per_10min: int, messages_per_day: int,
                 tts_chars_per_day: int, tts_chars_per_day_total: int, stt_per_day: int) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._burst: dict[str, deque[float]] = defaultdict(deque)
        self.messages_per_10min = messages_per_10min
        self.messages_per_day = messages_per_day
        self.tts_chars_per_day = tts_chars_per_day
        self.tts_chars_per_day_total = tts_chars_per_day_total
        self.stt_per_day = stt_per_day
        self._day, self._counts = self._load()

    def _load(self) -> tuple[str, dict[str, int]]:
        today = date.today().isoformat()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data.get("day") == today:
                return today, {k: int(v) for k, v in data.get("counts", {}).items()}
        except (OSError, ValueError):
            pass
        return today, {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": self._day, "counts": self._counts}), encoding="utf-8")
        tmp.replace(self._path)

    def _roll(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day, self._counts = today, {}

    def _add(self, key: str, amount: int, limit: int, message: str) -> None:
        if self._counts.get(key, 0) + amount > limit:
            raise LimitExceeded(message)
        self._counts[key] = self._counts.get(key, 0) + amount

    def message(self, visitor: str) -> None:
        with self._lock:
            now = time.monotonic()
            window = self._burst[visitor]
            while window and now - window[0] > 600:
                window.popleft()
            if len(window) >= self.messages_per_10min:
                raise LimitExceeded("傾得太快喇，休息幾分鐘再傾啦～")
            self._roll()
            self._add(f"msg:{visitor}", 1, self.messages_per_day, "今日已經傾咗好多，聽日再嚟搵我哋啦～")
            window.append(now)
            self._save()

    def tts(self, visitor: str, chars: int) -> None:
        with self._lock:
            self._roll()
            if self._counts.get("tts:total", 0) + chars > self.tts_chars_per_day_total:
                raise LimitExceeded("今日語音額度用晒，暫時只可以用文字傾偈。")
            self._add(f"tts:{visitor}", chars, self.tts_chars_per_day, "你今日嘅語音額度用晒，暫時用文字傾偈啦。")
            self._counts["tts:total"] = self._counts.get("tts:total", 0) + chars
            self._save()

    def stt(self, visitor: str) -> None:
        with self._lock:
            self._roll()
            self._add(f"stt:{visitor}", 1, self.stt_per_day, "今日語音輸入次數用晒，請打字傾偈。")
            self._save()

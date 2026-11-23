from pathlib import Path
from datetime import datetime
import shutil
import py_compile

root = Path(r"C:\AI-Girlfriend\openmimicry-main\openmimicry-main")

azure = root / "packages/openmimicry-voice/src/openmimicry/voice/tts/azure.py"
speech = root / "packages/openmimicry-voice/src/openmimicry/voice/controllers/speech.py"

files = [azure, speech]
originals = {}
updates = {}

def replace_once(content, old, new, label):
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected 1 match, found {count}. "
            "No files modified."
        )
    return content.replace(old, new, 1)

for path in files:
    originals[path] = path.read_text(encoding="utf-8-sig")

a = originals[azure]
s = originals[speech]

if 'on_chunk({"type": "lip_sync.frames"' in a:
    raise RuntimeError("Azure lip-sync callback already installed.")

if "def _publish_lip_sync_frames(" in s:
    raise RuntimeError("SpeechController lip-sync callback already installed.")

# Azure: send RMS frames before launching audio playback.
a = replace_once(
    a,
    "            self._mouth_frames = pcm_to_mouth_frames(pcm)",
    """            self._mouth_frames = pcm_to_mouth_frames(pcm)
            if on_chunk is not None:
                on_chunk({
                    "type": "lip_sync.frames",
                    "window_ms": 40,
                    "frames": list(self._mouth_frames),
                })""",
    "Azure RMS callback"
)

# SpeechController: import the new event.
s = replace_once(
    s,
    "    TTSFinished,",
    "    TTSFinished,\n    TTSLipSyncFrames,",
    "SpeechController event import"
)

# SpeechController: callback is scoped to this utterance.
old = """        play_task: asyncio.Task[None] | None = None
        try:
            play_task = asyncio.create_task(
                self._tts.speak(text_or_stream, config=tts_config),
"""

new = """        play_task: asyncio.Task[None] | None = None

        def _publish_lip_sync_frames(chunk: object) -> None:
            if self._current_utterance_id != utterance_id:
                return
            if self._current_tts_task is not asyncio.current_task():
                return
            if not isinstance(chunk, dict):
                return
            if chunk.get("type") != "lip_sync.frames":
                return

            frames = chunk.get("frames")
            window_ms = chunk.get("window_ms", 40)

            if not isinstance(frames, list):
                return

            try:
                event = TTSLipSyncFrames(
                    ts=_now(),
                    utterance_id=utterance_id,
                    window_ms=window_ms,
                    frames=frames,
                )
            except (TypeError, ValueError) as exc:
                _log.warning("Invalid lip-sync frames: %s", exc)
                return

            self._bus.publish(event)

        try:
            play_task = asyncio.create_task(
                self._tts.speak(
                    text_or_stream,
                    config=tts_config,
                    on_chunk=_publish_lip_sync_frames,
                ),
"""

s = replace_once(
    s,
    old,
    new,
    "SpeechController TTS callback"
)

updates[azure] = a
updates[speech] = s

# Validate syntax in memory before touching original files.
for path, content in updates.items():
    compile(content, str(path), "exec")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backups = {}

for path in files:
    backup = Path(str(path) + f".bak_a2_3b_{stamp}")
    shutil.copy2(path, backup)
    backups[path] = backup
    print("BACKUP:", backup)

try:
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")

    for path in files:
        py_compile.compile(str(path), doraise=True)

except BaseException:
    for path, backup in backups.items():
        shutil.copy2(backup, path)
    print("INSTALL FAILED - ORIGINAL FILES RESTORED")
    raise

print("A2-3B INSTALL PASSED")
print("Updated files: 2")
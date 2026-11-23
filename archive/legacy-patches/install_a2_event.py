from pathlib import Path
from datetime import datetime
import py_compile
import shutil

root = Path(r"C:\AI-Girlfriend\openmimicry-main\openmimicry-main")

events = root / "packages/openmimicry-core/src/openmimicry/core/schemas/events.py"
projection = root / "apps/backend/src/openmimicry_backend/projection.py"

files = [events, projection]
originals = {}
updated = {}
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 match, found {count}"
        )
    return text.replace(old, new, 1)

try:
    for path in files:
        originals[path] = path.read_text(encoding="utf-8-sig")

    e = originals[events]
    p = originals[projection]

    if "class TTSLipSyncFrames(" in e:
        raise RuntimeError("Lip-sync event already exists. No changes made.")

    if '"type": "lip_sync.frames"' in p:
        raise RuntimeError("Lip-sync projection already exists. No changes made.")

    e = replace_once(
        e,
        '    "TTSChunkSpoken",',
        '    "TTSChunkSpoken",\n    "TTSLipSyncFrames",',
        "Event export"
    )

    new_event = '''
class TTSLipSyncFrames(_Event):
    """RMS mouth frames for one TTS utterance."""

    kind: Literal["tts_lip_sync_frames"] = "tts_lip_sync_frames"
    utterance_id: str
    window_ms: int = Field(default=40, ge=1, le=1000)
    frames: list[Literal[0, 1, 2, 3]]


'''

    e = replace_once(
        e,
        'class TTSFinished(_Event):',
        new_event + 'class TTSFinished(_Event):',
        "Event class"
    )

    # Add to the discriminated union, not merely __all__.
    union_start = e.index("RuntimeEvent = Annotated[")
    union_end = e.index("RuntimeEventAdapter:", union_start)
    prefix = e[:union_start]
    union = e[union_start:union_end]
    suffix = e[union_end:]

    union = replace_once(
        union,
        "| TTSChunkSpoken",
        "| TTSChunkSpoken\n    | TTSLipSyncFrames",
        "RuntimeEvent union"
    )
    e = prefix + union + suffix

    p = replace_once(
        p,
        '    TTSChunkSpoken,',
        '    TTSChunkSpoken,\n    TTSLipSyncFrames,',
        "Projection import"
    )

    projection_case = '''
    if isinstance(event, TTSLipSyncFrames):
        return {
            "type": "lip_sync.frames",
            "utterance_id": event.utterance_id,
            "window_ms": event.window_ms,
            "frames": event.frames,
        }

'''

    p = replace_once(
        p,
        '    if isinstance(event, TranscriptPreview):',
        projection_case + '    if isinstance(event, TranscriptPreview):',
        "Projection handler"
    )

    updated[events] = e
    updated[projection] = p

    backups = {}
    for path in files:
        backup = Path(str(path) + f".bak_a2_{stamp}")
        shutil.copy2(path, backup)
        backups[path] = backup
        print("BACKUP:", backup)

    try:
        for path, content in updated.items():
            path.write_text(content, encoding="utf-8")

        for path in files:
            py_compile.compile(str(path), doraise=True)

    except Exception:
        for path, backup in backups.items():
            shutil.copy2(backup, path)
        print("Installation failed. Original files restored.")
        raise

    print("A2 EVENT INSTALL PASSED")
    print("Files updated:", len(files))

except Exception as exc:
    print("A2 EVENT INSTALL FAILED:", exc)
    raise
$ErrorActionPreference = "Stop"

$root = "C:\AI-Girlfriend\openmimicry-main\openmimicry-main"
$target = Join-Path $root "packages\openmimicry-voice\src\openmimicry\voice\tts\lip_sync.py"

if (Test-Path $target) {
    Write-Host "lip_sync.py already exists. No overwrite." -ForegroundColor Yellow
    exit 0
}

$code = @"
"""Audio amplitude analysis for 2D lip-sync animation."""

from __future__ import annotations

import audioop


def pcm_to_mouth_frames(
    pcm: bytes,
    *,
    sample_rate: int = 24000,
    window_ms: int = 40,
) -> list[int]:
    """Convert signed 16-bit mono PCM into mouth levels 0-3."""

    if sample_rate <= 0 or window_ms <= 0:
        raise ValueError("sample_rate and window_ms must be positive")

    if len(pcm) % 2:
        raise ValueError("PCM data must contain complete 16-bit samples")

    samples_per_window = max(1, sample_rate * window_ms // 1000)
    bytes_per_window = samples_per_window * 2

    if not pcm:
        return []

    rms_values = []

    for offset in range(0, len(pcm), bytes_per_window):
        chunk = pcm[offset:offset + bytes_per_window]
        rms_values.append(audioop.rms(chunk, 2))

    peak = max(rms_values)

    if peak == 0:
        return [0] * len(rms_values)

    frames = []

    for rms in rms_values:
        level = rms / peak

        if level < 0.06:
            frames.append(0)
        elif level < 0.22:
            frames.append(1)
        elif level < 0.55:
            frames.append(2)
        else:
            frames.append(3)

    return frames
"@

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $code, $utf8)

Write-Host "A2 RMS analyzer installed successfully!" -ForegroundColor Green
Write-Host "File: $target"
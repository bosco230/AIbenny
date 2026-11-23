$ErrorActionPreference = "Stop"

$root = "C:\AI-Girlfriend\openmimicry-main\openmimicry-main"
$target = Join-Path $root "packages\openmimicry-voice\src\openmimicry\voice\tts\azure.py"
$analyzer = Join-Path $root "packages\openmimicry-voice\src\openmimicry\voice\tts\lip_sync.py"

if (-not (Test-Path $analyzer)) {
    throw "lip_sync.py missing. Installation stopped."
}

$content = [System.IO.File]::ReadAllText($target)

if ($content.Contains("self._mouth_frames = pcm_to_mouth_frames(pcm)")) {
    Write-Host "A2 Azure integration already installed." -ForegroundColor Yellow
    exit 0
}

$oldImport = "from .system_command import _collect_text, _playback_command"
$newImport = "from .lip_sync import pcm_to_mouth_frames`n" + $oldImport

$oldInit = "        self._is_speaking = False"
$newInit = "        self._is_speaking = False`n        self._mouth_frames: list[int] = []"

$oldPCM = "            pcm = await asyncio.to_thread(self._synthesize, text)"
$newPCM = $oldPCM + "`n            self._mouth_frames = pcm_to_mouth_frames(pcm)"

foreach ($needle in @($oldImport, $oldPCM)) {
    if (-not $content.Contains($needle)) {
        throw "Expected code not found: $needle"
    }
}

if (-not $content.Contains($oldInit)) {
    throw "Azure initialization code not found."
}

$backup = "$target.bak_a2_$(Get-Date -Format yyyyMMdd_HHmmss)"
Copy-Item $target $backup -ErrorAction Stop

$content = $content.Replace($oldImport, $newImport)
$content = $content.Replace($oldInit, $newInit)
$content = $content.Replace($oldPCM, $newPCM)

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $content, $utf8)

Write-Host "A2 Azure RMS integration installed!" -ForegroundColor Green
Write-Host "Backup: $backup"
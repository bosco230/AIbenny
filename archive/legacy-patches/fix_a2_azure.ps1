$ErrorActionPreference = "Stop"

$root = "C:\AI-Girlfriend\openmimicry-main\openmimicry-main"
$target = Join-Path $root "packages\openmimicry-voice\src\openmimicry\voice\tts\azure.py"

$content = [System.IO.File]::ReadAllText($target)

$old = @"
        finally:
            self._process = None
            self._is_speaking = False
        self._mouth_frames: list[int] = []
"@

$new = @"
        finally:
            self._process = None
            self._is_speaking = False
"@

$normalized = $content.Replace("`r`n", "`n")
$old = $old.Replace("`r`n", "`n")
$new = $new.Replace("`r`n", "`n")

if (-not $normalized.Contains($old)) {
    throw "Expected finally block not found. No changes made."
}

$backup = "$target.bak_fix_$(Get-Date -Format yyyyMMdd_HHmmss)"
Copy-Item $target $backup -ErrorAction Stop

$normalized = $normalized.Replace($old, $new)

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $normalized, $utf8)

Write-Host "A2 Azure cleanup completed!" -ForegroundColor Green
Write-Host "Backup: $backup"
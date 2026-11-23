$ErrorActionPreference = "Stop"

$file = ".\apps\desktop\frontend\src\runtimes\sprite2d\Sprite2DRuntime.tsx"
$fullPath = (Resolve-Path $file).Path
$content = [System.IO.File]::ReadAllText($fullPath)

$marker = '    const intervalMs = Math.max(1, Math.floor(1000 / fps));'

if ($content.Contains('Natural speech animation: varied mouth openings')) {
    Write-Host "Already installed. No changes made." -ForegroundColor Yellow
}
elseif (-not $content.Contains($marker)) {
    Write-Host "Insertion point not found. No changes made." -ForegroundColor Red
}
else {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupFile = "$fullPath.bak_$stamp"

    Copy-Item $fullPath $backupFile -ErrorAction Stop

    $insert = @"
    // Natural speech animation: varied mouth openings and brief pauses.
    if (automaticState === "speaking" && frames.length === 4) {
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;
      let previousFrame = 0;

      const animateMouth = () => {
        if (cancelled) return;

        const pause = Math.random() < 0.12;
        let nextFrame: number;

        if (pause) {
          nextFrame = 0;
        } else {
          const choices = [1, 2, 3, 2, 1, 0];
          nextFrame = choices[Math.floor(Math.random() * choices.length)];

          if (nextFrame === previousFrame) {
            nextFrame = (nextFrame + 1) % 4;
          }
        }

        previousFrame = nextFrame;
        setCurrentIdx(nextFrame);

        const delay = pause
          ? 130 + Math.random() * 140
          : 85 + Math.random() * 95;

        timer = setTimeout(animateMouth, delay);
      };

      setCurrentIdx(0);
      animateMouth();

      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }

"@

    $updated = $content.Replace($marker, $insert + "`n" + $marker)

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($fullPath, $updated, $utf8)

    Write-Host "Natural speech animation installed!" -ForegroundColor Green
    Write-Host "Backup: $backupFile"
}
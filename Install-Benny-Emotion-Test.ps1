$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$source = Join-Path $root "apps\desktop\frontend\src\runtimes\sprite2d\Sprite2DRuntime.tsx"
$assetRoot = Join-Path $root "characters\ai_girlfriend"
$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (!(Test-Path $source)) { throw "Run from OpenMimicry project root." }
$original = [System.IO.File]::ReadAllText($source)
if ($original.Contains("BENNY_EMOTION_TEST_V1")) { Write-Host "ALREADY INSTALLED"; exit 0 }
$oldStates = '    "happy",' + "`n" + '  ];'
$newStates = '    "happy",' + "`n" + '    "sad",' + "`n" + '    "angry",' + "`n" + '    "surprised",' + "`n" + '    "sad_speaking",' + "`n" + '    "angry_speaking",' + "`n" + '    "surprised_speaking",' + "`n" + '  ];'
$oldCounts = '    happy_speaking: 4,'
$newCounts = '    happy_speaking: 4,' + "`n" + '    sad: 1,' + "`n" + '    angry: 1,' + "`n" + '    surprised: 1,' + "`n" + '    sad_speaking: 4,' + "`n" + '    angry_speaking: 4,' + "`n" + '    surprised_speaking: 4,'
$oldSelect = @'
  const automaticFrames = isAiGirlfriend
    ? getStateFrames(automaticState === "speaking" && happySpeechEnabled
        ? "happy_speaking" : automaticState)
    : null;
'@
$newSelect = @'
  // BENNY_EMOTION_TEST_V1: Preserve RMS mouth indexes across emotion sets.
  const emotion = props.projection?.directive?.emotion;
  const speakingEmotion =
    emotion === "sad" || emotion === "angry" || emotion === "surprised"
      ? emotion
      : null;
  const selectedState =
    automaticState === "speaking"
      ? happySpeechEnabled
        ? "happy_speaking"
        : speakingEmotion
          ? `${speakingEmotion}_speaking`
          : "speaking"
      : automaticState;
  const automaticFrames = isAiGirlfriend
    ? getStateFrames(selectedState)
    : null;
'@
$normalized = $original.Replace("`r`n","`n")
foreach ($anchor in @($oldStates,$oldCounts,$oldSelect)) {
  if (!$normalized.Contains($anchor.Replace("`r`n","`n"))) { throw "Frontend does not match uploaded version. Nothing changed." }
}
$patched = $normalized.Replace($oldStates,$newStates).Replace($oldCounts,$newCounts).Replace($oldSelect,$newSelect.Replace("`r`n","`n"))
$backup = "$source.before-emotion-$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
Copy-Item $source $backup
try {
  foreach ($emotion in @("sad","angry","surprised")) {
    foreach ($folder in @($emotion, "${emotion}_speaking")) {
      $from = Join-Path $packageRoot "characters\ai_girlfriend\$folder"
      if (!(Test-Path $from)) { throw "Missing images: $folder" }
      $to = Join-Path $assetRoot $folder
      if (Test-Path $to) { throw "Destination exists: $to. Refusing overwrite." }
      Copy-Item -Recurse -LiteralPath $from -Destination $to
    }
  }
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($source,$patched,$utf8)
} catch {
  Copy-Item $backup $source -Force
  throw
}
Write-Host "PATCH OK"
Write-Host "BACKUP: $backup"
Write-Host "TEST: http://127.0.0.1:5173/?aiState=sad#/overlay"
Write-Host "TEST: http://127.0.0.1:5173/?aiState=angry#/overlay"
Write-Host "TEST: http://127.0.0.1:5173/?aiState=surprised#/overlay"

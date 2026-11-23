$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root "apps\desktop\frontend\src\runtimes\sprite2d\Sprite2DRuntime.tsx"
$images = Join-Path $root "characters\ai_girlfriend\happy_speaking"
if (!(Test-Path -PathType Leaf $target)) { throw "Please run this script from the OpenMimicry project root." }
if (!(Test-Path -PathType Container (Join-Path $scriptDir "happy_speaking"))) { throw "Missing happy_speaking image folder. Extract the entire ZIP first." }
$enc = New-Object System.Text.UTF8Encoding($false)
$code = [System.IO.File]::ReadAllText($target)
if ($code.Contains("BENNY_HAPPY_SPEECH_V1")) { Write-Host "ALREADY INSTALLED"; exit 0 }
if (!$code.Contains("const [showHappy, setShowHappy] = useState(false);") -or !$code.Contains("happyPendingRef.current = true;")) {
  throw "Unexpected frontend version. No changes made."
}
$before = $code
$old = '  const [showHappy, setShowHappy] = useState(false);'
$new = '  const [showHappy, setShowHappy] = useState(false);' + "`n" + '  const [happySpeechEnabled, setHappySpeechEnabled] = useState(false); // BENNY_HAPPY_SPEECH_V1'
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "State anchor mismatch" }
$code = $code.Replace($old,$new)
$old = '    happy: 3,'; $new = "    happy: 3,`n    happy_speaking: 4,"
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "Frame anchor mismatch" }
$code = $code.Replace($old,$new)
$old = '      happyPendingRef.current = true;'
$new = "      happyPendingRef.current = true;`n      setHappySpeechEnabled(true);"
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "Happy anchor mismatch" }
$code = $code.Replace($old,$new)
$old = '      happyPendingRef.current = false;' + "`n" + '      cancelHappyTimer();'
$new = '      happyPendingRef.current = false;' + "`n" + '      setHappySpeechEnabled(false);' + "`n" + '      cancelHappyTimer();'
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "Reset anchor mismatch" }
$code = $code.Replace($old,$new)
$old = '  const automaticFrames = isAiGirlfriend' + "`n" + '    ? getStateFrames(automaticState)' + "`n" + '    : null;'
$new = '  const automaticFrames = isAiGirlfriend' + "`n" + '    ? getStateFrames(automaticState === "speaking" && happySpeechEnabled' + "`n" + '        ? "happy_speaking" : automaticState)' + "`n" + '    : null;'
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "Frame selection anchor mismatch" }
$code = $code.Replace($old,$new)
$old = '        if (msg.status === "finished" && happyPendingRef.current) {'
$new = '        setHappySpeechEnabled(false);' + "`n" + '        if (msg.status === "finished" && happyPendingRef.current) {'
if ($code.Split([string[]]@($old),[StringSplitOptions]::None).Count -ne 2) { throw "Speech finish anchor mismatch" }
$code = $code.Replace($old,$new)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "$target.before-happy-speaking-$stamp.bak"
Copy-Item -LiteralPath $target -Destination $backup -ErrorAction Stop
try {
  New-Item -ItemType Directory -Path $images -Force | Out-Null
  foreach ($i in 0..3) {
    $name = "{0:D3}.png" -f $i
    Copy-Item -LiteralPath (Join-Path $scriptDir "happy_speaking\$name") -Destination (Join-Path $images $name) -Force
  }
  [System.IO.File]::WriteAllText($target,$code,$enc)
} catch {
  Copy-Item -LiteralPath $backup -Destination $target -Force
  throw
}
Write-Host "PATCH OK"
Write-Host "BACKUP: $backup"
Write-Host "IMAGES: $images"
Write-Host "UPDATED: $target"

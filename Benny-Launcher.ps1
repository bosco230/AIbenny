param([ValidateSet('start','stop')][string]$Action='start')
$ErrorActionPreference='Stop'
$Root='C:\AI-Girlfriend\openmimicry-main\openmimicry-main'
$State=Join-Path $Root '.benny-launcher'
$Python=Join-Path $Root '.venv\Scripts\python.exe'
$BackendUrl='http://127.0.0.1:8000/health'
$FrontendUrl='http://127.0.0.1:5173/'
$OllamaUrl='http://127.0.0.1:11434/api/tags'
New-Item -ItemType Directory -Force -Path $State | Out-Null
function Test-Port([int]$Port) {
  $c=New-Object System.Net.Sockets.TcpClient
  try { $ar=$c.BeginConnect('127.0.0.1',$Port,$null,$null); if(-not $ar.AsyncWaitHandle.WaitOne(800)){return $false}; $c.EndConnect($ar); return $true } catch {return $false} finally {$c.Close()}
}
function Test-Http([string]$Url) {
  try { $r=Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3; return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) } catch {return $false}
}
function Wait-Port([int]$Port,[int]$Seconds) {
  for($i=0;$i -lt $Seconds;$i++){if(Test-Port $Port){return $true};Start-Sleep -Seconds 1};return $false
}
function Start-Managed([string]$Name,[string]$Exe,[string[]]$Arguments,[string]$WorkingDirectory) {
  $out=Join-Path $State "$Name.stdout.log"; $err=Join-Path $State "$Name.stderr.log"
  $p=Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
  Set-Content -Path (Join-Path $State "$Name.pid") -Value $p.Id
  Write-Host "$Name started (PID $($p.Id))."
}
function Stop-Managed([string]$Name) {
  $f=Join-Path $State "$Name.pid"
  if(-not (Test-Path $f)){Write-Host "${Name}: not managed by launcher.";return}
  $idText=(Get-Content $f -Raw).Trim()
  $p=Get-Process -Id ([int]$idText) -ErrorAction SilentlyContinue
  if($p){
    $expected=if($Name -eq 'backend'){'python'}elseif($Name -eq 'frontend'){'cmd'}else{'ollama'}
    if($p.ProcessName -notlike "$expected*"){Write-Warning "$Name PID now belongs to $($p.ProcessName); skipping."} else {
      if($Name -eq 'frontend'){Write-Warning 'Frontend process tree may include child processes. Closing launcher-owned console process only.'}
      Stop-Process -Id $p.Id -ErrorAction SilentlyContinue
      Write-Host "$Name stopped (PID $($p.Id))."
    }
  }
  Remove-Item $f -ErrorAction SilentlyContinue
}
if($Action -eq 'stop') {
  Stop-Managed 'frontend'
  Stop-Managed 'backend'
  Write-Host 'Ollama left running to avoid disrupting other apps.'
  exit 0
}
if(-not(Test-Path $Python)){throw "Python venv missing: $Python"}
if(-not(Test-Path (Join-Path $Root 'apps\desktop\frontend\package.json'))){throw 'Frontend project missing.'}
$ollama=(Get-Command ollama.exe -ErrorAction SilentlyContinue).Source
if(-not $ollama){$ollama=Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'}
if(-not(Test-Port 11434)){
  if(-not(Test-Path $ollama)){throw 'Ollama executable not found.'}
  Start-Managed 'ollama' $ollama @('serve') $Root
  if(-not(Wait-Port 11434 25)){throw 'Ollama did not start. Check launcher logs.'}
} else {Write-Host 'Ollama already listening on 11434.'}
if(-not(Test-Port 8000)){
  $env:OLLAMA_API_BASE = 'http://127.0.0.1:11434'
  Start-Managed 'backend' $Python @('-m','uvicorn','openmimicry_backend.main:app','--host','127.0.0.1','--port','8000','--loop','asyncio') $Root
  if(-not(Wait-Port 8000 40)){throw 'Backend did not open port 8000. Check launcher logs.'}
} else {Write-Host 'Port 8000 already occupied. Not starting duplicate backend.'}
if(-not(Test-Port 5173)){
  $pnpm=(Get-Command pnpm.cmd -ErrorAction SilentlyContinue).Source
  if(-not $pnpm){throw 'pnpm.cmd not found in PATH.'}
  Start-Managed 'frontend' $env:ComSpec @('/d','/s','/c',"`"`"$pnpm`" --dir apps/desktop/frontend dev --host 127.0.0.1 --port 5173 --strictPort`"") $Root
  if(-not(Wait-Port 5173 30)){throw 'Frontend did not open port 5173. Check launcher logs.'}
} else {Write-Host 'Frontend already listening on 5173.'}
Write-Host 'Benny services are listening. Opening frontend.'
Start-Process $FrontendUrl
Write-Host 'Done. For native Tauri overlay, continue using your existing desktop launcher until verified.'

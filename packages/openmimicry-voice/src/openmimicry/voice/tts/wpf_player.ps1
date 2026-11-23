param(
    [Parameter(Mandatory=$true)]
    [string]$WavPath,

    [ValidateRange(1, 600)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$script:PlaybackCompleted = $false
$script:PlaybackResult = 1
$script:PlaybackError = ""
$script:MediaDurationSeconds = $null
$script:Player = $null
$script:Frame = $null
$script:Timer = $null

function Complete-Playback {
    param(
        [int]$Code,
        [string]$Reason
    )

    if ($script:PlaybackCompleted) {
        return
    }

    $script:PlaybackCompleted = $true
    $script:PlaybackResult = $Code
    $script:PlaybackError = $Reason

    if ($null -ne $script:Frame) {
        $script:Frame.Continue = $false
    }
}

try {
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase

    if (
        [System.Threading.Thread]::CurrentThread.GetApartmentState() -ne
        [System.Threading.ApartmentState]::STA
    ) {
        throw "WPF_REQUIRES_STA"
    }

    if (-not [System.IO.File]::Exists($WavPath)) {
        throw "WAV_NOT_FOUND"
    }

    $script:Player = New-Object System.Windows.Media.MediaPlayer
    $script:Frame = New-Object System.Windows.Threading.DispatcherFrame
    $script:Timer = New-Object System.Windows.Threading.DispatcherTimer

    $script:Timer.Interval = [TimeSpan]::FromSeconds(
        $TimeoutSeconds
    )

    $script:Player.add_MediaOpened({
        if ($script:PlaybackCompleted) {
            return
        }

        try {
            $duration = $script:Player.NaturalDuration

            if ($duration.HasTimeSpan) {
                $script:MediaDurationSeconds = (
                    $duration.TimeSpan.TotalSeconds
                )
            }

            $script:Player.Play()
        }
        catch {
            Complete-Playback `
                -Code 2 `
                -Reason ("PLAY_FAILED: " + $_.Exception.Message)
        }
    })

    $script:Player.add_MediaEnded({
        Complete-Playback -Code 0 -Reason "MEDIA_ENDED"
    })

    $script:Player.add_MediaFailed({
        param($sender, $eventArgs)

        $detail = "MEDIA_FAILED"

        if ($null -ne $eventArgs.ErrorException) {
            $detail += ": " +
                $eventArgs.ErrorException.GetType().FullName +
                ": " +
                $eventArgs.ErrorException.Message
        }

        Complete-Playback -Code 3 -Reason $detail
    })

    $script:Timer.add_Tick({
        Complete-Playback -Code 4 -Reason "PLAYBACK_TIMEOUT"
    })

    $uri = [System.Uri]::new(
        [System.IO.Path]::GetFullPath($WavPath),
        [System.UriKind]::Absolute
    )

    $script:Timer.Start()
    $script:Player.Open($uri)

    if (-not $script:PlaybackCompleted) {
        [System.Windows.Threading.Dispatcher]::PushFrame(
            $script:Frame
        )
    }
}
catch {
    Complete-Playback `
        -Code 5 `
        -Reason ("PLAYER_EXCEPTION: " + $_.Exception.Message)
}
finally {
    $script:CleanupErrors = @()

    if ($null -ne $script:Timer) {
        try {
            $script:Timer.Stop()
        }
        catch {
            $script:CleanupErrors += (
                "TIMER_STOP_CLEANUP_FAILED: " +
                $_.Exception.Message
            )
        }
    }

    if ($null -ne $script:Player) {
        try {
            $script:Player.Stop()
        }
        catch {
            $script:CleanupErrors += (
                "PLAYER_STOP_CLEANUP_FAILED: " +
                $_.Exception.Message
            )
        }

        try {
            $script:Player.Close()
        }
        catch {
            $script:CleanupErrors += (
                "PLAYER_CLOSE_CLEANUP_FAILED: " +
                $_.Exception.Message
            )
        }
    }

    if ($script:CleanupErrors.Count -gt 0) {
        foreach ($errorMessage in $script:CleanupErrors) {
            [Console]::Error.WriteLine($errorMessage)
        }

        if ($script:PlaybackResult -eq 0) {
            $script:PlaybackResult = 8
            $script:PlaybackError = "PLAYBACK_CLEANUP_FAILED"
        }
    }
}
if ($null -ne $script:MediaDurationSeconds) {
    [Console]::Error.WriteLine(
        "MEDIA_DURATION_SECONDS: $script:MediaDurationSeconds"
    )
}

if ($script:PlaybackResult -ne 0) {
    [Console]::Error.WriteLine($script:PlaybackError)
}

exit $script:PlaybackResult


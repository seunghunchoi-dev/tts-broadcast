# SAPI (System.Speech) persistent worker.
# Protocol: one base64(UTF-8 JSON) request per line on stdin,
#           one base64(UTF-8 JSON) response per line on stdout.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Send($obj) {
    $json = $obj | ConvertTo-Json -Compress
    [Console]::Out.WriteLine([Convert]::ToBase64String($utf8.GetBytes($json)))
    [Console]::Out.Flush()
}

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line.Trim() -eq '') { continue }
    try {
        $req = $utf8.GetString([Convert]::FromBase64String($line.Trim())) | ConvertFrom-Json
        if ($req.cmd -eq 'voices') {
            $names = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
            Send @{ ok = $true; voices = $names }
        }
        elseif ($req.cmd -eq 'speak') {
            if ($req.voice) {
                $synth.SelectVoice([string]$req.voice)
            }
            elseif ($req.culture) {
                $ci = New-Object System.Globalization.CultureInfo([string]$req.culture)
                $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, $ci)
            }
            $synth.Rate = [int]$req.rate
            $synth.Volume = [int]$req.volume
            $synth.SetOutputToWaveFile([string]$req.out)
            try {
                if ($req.ssml) { $synth.SpeakSsml([string]$req.text) }
                else { $synth.Speak([string]$req.text) }
            }
            finally {
                $synth.SetOutputToNull()
            }
            Send @{ ok = $true }
        }
        else {
            Send @{ ok = $false; error = "unknown cmd" }
        }
    }
    catch {
        Send @{ ok = $false; error = $_.Exception.Message }
    }
}

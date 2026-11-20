param([string]$Json, [string]$OutDir, [string]$Voice = "Microsoft Zira Desktop", [int]$Rate = -1)
Add-Type -AssemblyName System.Speech
$lines = Get-Content -Raw -Encoding UTF8 $Json | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($Voice)
$s.Rate = $Rate
for ($i = 0; $i -lt $lines.Count; $i++) {
    $path = Join-Path $OutDir ("n{0:D2}.wav" -f $i)
    $s.SetOutputToWaveFile($path)
    $s.Speak($lines[$i])
    $s.SetOutputToNull()
}
$s.Dispose()
Write-Output ("wrote " + $lines.Count + " files")

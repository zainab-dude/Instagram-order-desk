# A3 experiments, in order. Run from the project root with the stack up:
#   powershell -ExecutionPolicy Bypass -File scripts\run_experiments.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_experiments.ps1 -Stages failure   (one stage only)
# Stages: baseline (A only), rr (Part C), weighted, least (RR vs least request with delay on B), failure.
# Every run writes results\<name>.json (client), .requests.json, .prometheus.json, .es.json, .summary.json,
# .envoy.yaml (config used) and .delays.json (delay files used). Normal state is restored at the end.
param(
    [string[]]$Stages = @("baseline", "rr", "weighted", "least", "failure"),
    [double]$Rate = 20,
    [int]$Duration = 60,
    [int]$DelayMs = 200,
    [int]$GapSeconds = 30,
    [string]$Py = ".\.venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force results | Out-Null

function Log($msg) { Write-Host ("[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("HH:mm:ss"), $msg) }

function Set-Delay([int]$b) {
    Set-Content -Path experiments\lb\delay-b.txt -Value "$b" -Encoding ascii
    Log "delay-b.txt = $b ms"
}

function Wait-Envoy([switch]$AllHealthy) {
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $ready = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:9901/ready).Content.Trim()
            if ($ready -eq "LIVE") {
                if (-not $AllHealthy) { return }
                $c = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://localhost:9901/clusters").Content
                if ($c -notmatch "health_flags::/failed") { return }
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Envoy not ready"
}

function Set-Mode([string]$mode, [switch]$Health) {
    $extra = @(); if ($Health) { $extra = @("--health") }
    & $Py scripts\make_envoy_config.py $mode @extra
    docker compose restart envoy | Out-Null
    Wait-Envoy -AllHealthy:$Health
    Start-Sleep -Seconds 3
    Log "Envoy mode: $mode $extra"
}

function Save-Config([string]$name) {
    Copy-Item envoy\envoy.yaml "results\$name.envoy.yaml"
    $d = @{}
    foreach ($r in "a", "b", "c") { $d["delay-$r.txt"] = (Get-Content "experiments\lb\delay-$r.txt" -Raw).Trim() }
    $d | ConvertTo-Json | Set-Content "results\$name.delays.json" -Encoding utf8
}

function Run-Load([string]$name, [string]$iface) {
    Save-Config $name
    Log "RUN $name ($iface, $Rate rps, $Duration s)"
    & $Py scripts\lb_client.py --interface $iface --rate $Rate --duration $Duration --out "results\$name.json" --run ("{0}-{1}" -f $name, (Get-Date).ToUniversalTime().ToString("HHmmss"))
    & $Py scripts\collect_run.py "results\$name.json"
    Start-Sleep -Seconds $GapSeconds   # visible gap between runs on the dashboard
}

function Run-Failure([string]$name, [string]$iface) {
    Save-Config $name
    Log "FAILURE RUN $name ($iface, 90 s; stop B at ~30 s, start at ~60 s)"
    & $Py scripts\failure_run.py --interface $iface --out "results\$name.json"
    & $Py scripts\collect_run.py "results\$name.json"
    Start-Sleep -Seconds $GapSeconds
}

Set-Delay 0
if ($Stages -contains "baseline") {
    Set-Mode "a-only"
    Run-Load "b-aonly-http" "http"
    Run-Load "b-aonly-grpc" "grpc"
}
if ($Stages -contains "rr") {
    Set-Mode "rr"
    Run-Load "c-rr-http" "http"
    Run-Load "c-rr-grpc" "grpc"
}
if ($Stages -contains "weighted") {
    Set-Mode "weighted"
    Run-Load "d1-weighted-http" "http"
    Run-Load "d1-weighted-grpc" "grpc"
    Set-Mode "rr"
}
if ($Stages -contains "least") {
    Set-Mode "rr"
    Set-Delay $DelayMs
    Run-Load "d2-rr-delayB-http" "http"
    Run-Load "d2-rr-delayB-grpc" "grpc"
    Set-Mode "least"
    Run-Load "d2-least-delayB-http" "http"
    Run-Load "d2-least-delayB-grpc" "grpc"
    Set-Delay 0
    Set-Mode "rr"
}
if ($Stages -contains "failure") {
    Set-Mode "rr" -Health      # restart also resets Envoy's 300 s DNS refresh timer
    Run-Failure "d3-fail-http" "http"
    Wait-Envoy -AllHealthy
    Set-Mode "rr" -Health
    Run-Failure "d3-fail-grpc" "grpc"
    docker compose start app-b grpc-b | Out-Null
    Set-Mode "rr"
}
Set-Delay 0
Log "done; Envoy is back in round robin, delays are 0, all replicas started"

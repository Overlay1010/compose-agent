# 개발 서버 켜기: 백엔드(8100) + 프론트엔드(5174).
# 같은 포트를 잡고 있던 옛 서버(창을 닫아도 남는 uvicorn · vite)를 먼저 끄고 새로 켠다. Ctrl+C로 둘 다 끈다.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'backend\compose_venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "backend\compose_venv가 없어요. README의 '실행' 순서대로 먼저 만들어 주세요."
}

function Stop-Port([int]$port) {
    # uvicorn --reload는 부모 · 자식이 함께 포트를 잡을 수 있어서, 빌 때까지 몇 번 확인한다
    for ($try = 0; $try -lt 5; $try++) {
        $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        if (-not $owners) { return }
        foreach ($id in $owners) {
            Write-Host "포트 $port 를 잡고 있던 프로세스 $id 를 끕니다"
            taskkill /PID $id /T /F | Out-Null
        }
        Start-Sleep -Milliseconds 500
    }
    throw "포트 $port 가 아직 사용 중이에요."
}

Stop-Port 8100
Stop-Port 5174

$backend = Start-Process $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8100' `
    -WorkingDirectory (Join-Path $root 'backend') -NoNewWindow -PassThru
$frontend = Start-Process 'npm.cmd' -ArgumentList 'run', 'dev' `
    -WorkingDirectory (Join-Path $root 'frontend') -NoNewWindow -PassThru
Write-Host ''
Write-Host '브라우저: http://localhost:5174   API 문서: http://localhost:8100/docs   (끄기: Ctrl+C)'
Write-Host ''

try {
    # 하나만 꺼져도(오류로 죽음 등) 다른 쪽도 끈다
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Milliseconds 500 }
} finally {
    $ErrorActionPreference = 'SilentlyContinue'  # 이미 꺼진 프로세스면 taskkill이 오류를 내지만 상관없다
    foreach ($p in $backend, $frontend) { taskkill /PID $p.Id /T /F 2>$null | Out-Null }
}

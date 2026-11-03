# 개발 서버 켜기: 백엔드(8100) · 프론트엔드(5174)를 각각 새 창으로 연다. 끌 때는 그 창을 닫는다.
# 같은 포트를 잡고 있던 옛 서버(창을 닫아도 남는 uvicorn · vite)를 먼저 끈다.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 백엔드 자동 다시 켜기는 uvicorn --reload 대신 watchfiles로 한다: Windows에서 --reload는 옛 서버에 Ctrl+C를 보내 끝나길 기다리는데,
# 그 신호가 닿지 않아 "Reloading..."에서 멈춘 채 옛 코드로 계속 돌았다 (2026-11-04, 새 도구가 서버에 안 들어감).
# watchfiles는 끝나지 않으면 3초 뒤 강제로 끄고 새로 켠다. 두 서버를 한 창에 두지 않는 것도 Ctrl+C가 창 전체에 가서다.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'backend\compose_venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "backend\compose_venv가 없어요. README의 '실행' 순서대로 먼저 만들어 주세요."
}

function Stop-Port([int]$port) {
    # 감시 프로세스 · 서버가 함께 포트를 잡을 수 있어서, 빌 때까지 몇 번 확인한다
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

# 전에 이 스크립트로 연 창(서버가 꺼진 채 남은 cmd 창 포함)을 닫는다 — 창이 쌓여 어느 게 지금 서버인지 헷갈리지 않게
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -match 'title compose-agent (backend|frontend)' } |
    ForEach-Object {
        Write-Host "전에 연 창 $($_.ProcessId) 를 닫습니다"
        taskkill /PID $_.ProcessId /T /F | Out-Null
    }

Stop-Port 8100
Stop-Port 5174

# cmd /k: 서버가 오류로 꺼져도 창이 남아 메시지를 볼 수 있다
Start-Process cmd -ArgumentList '/k', ("title compose-agent backend :8100 && `"$python`" -m watchfiles --filter python --sigint-timeout 3 " +
    "`"compose_venv\Scripts\python.exe -m uvicorn app.main:app --port 8100`" app") `
    -WorkingDirectory (Join-Path $root 'backend')
Start-Process cmd -ArgumentList '/k', 'title compose-agent frontend :5174 && npm run dev' `
    -WorkingDirectory (Join-Path $root 'frontend')
Write-Host '백엔드 · 프론트엔드를 새 창으로 열었어요. 브라우저: http://localhost:5174   API 문서: http://localhost:8100/docs'

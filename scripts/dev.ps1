# 개발 서버 켜기: 백엔드(8100) · 프론트엔드(5174)를 각각 새 창으로 연다. 끌 때는 그 창을 닫는다.
# 같은 포트를 잡고 있던 옛 서버(창을 닫아도 남는 uvicorn · vite)를 먼저 끈다.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 두 서버를 한 창에 두지 않는 이유: uvicorn --reload가 다시 켤 때 같은 창의 모든 프로세스에 Ctrl+C를 보내서 vite까지 꺼진다.
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

# cmd /k: 서버가 오류로 꺼져도 창이 남아 메시지를 볼 수 있다
Start-Process cmd -ArgumentList '/k', "title compose-agent backend :8100 && `"$python`" -m uvicorn app.main:app --reload --port 8100" `
    -WorkingDirectory (Join-Path $root 'backend')
Start-Process cmd -ArgumentList '/k', 'title compose-agent frontend :5174 && npm run dev' `
    -WorkingDirectory (Join-Path $root 'frontend')
Write-Host '백엔드 · 프론트엔드를 새 창으로 열었어요. 브라우저: http://localhost:5174   API 문서: http://localhost:8100/docs'

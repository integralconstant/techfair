param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$Console,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw '실행 환경이 아직 설치되지 않았어요. 먼저 이 폴더의 install.cmd를 실행해 주세요.'
    }
    if ($Console) {
        & $python -X utf8 server.py --port $Port
        if ($LASTEXITCODE -ne 0) { throw '서버 실행에 실패했습니다. 위 오류를 확인하세요.' }
    } else {
        if (-not (Test-Path -LiteralPath $pythonw)) { throw '실행 환경이 올바르지 않아요. install.cmd로 다시 설치해 주세요.' }
        $launcher = Join-Path $PSScriptRoot 'launcher.py'
        $launcherArguments = @('-X', 'utf8', ('"{0}"' -f $launcher), '--port', $Port)
        if ($NoBrowser) { $launcherArguments += '--no-browser' }
        Start-Process -FilePath $pythonw -ArgumentList $launcherArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    }
} catch {
    if ($Console) { throw }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, '두피 관리 서비스 실행', 'OK', 'Warning') | Out-Null
    exit 1
} finally {
    Pop-Location
}

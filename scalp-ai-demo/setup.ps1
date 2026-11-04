param([switch]$WithBrowserTests)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11~3.14를 설치한 뒤 다시 실행하세요.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch 설치에 실패했습니다.' }
    $requirementsFile = if ($WithBrowserTests) { 'requirements-dev.txt' } else { 'requirements.txt' }
    & '.\.venv\Scripts\python.exe' -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) { throw '웹 서버 의존성 설치에 실패했습니다.' }
    Write-Output '설치가 완료됐어요. start.cmd를 더블클릭하면 웹이 자동으로 열립니다.'
} finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop '두피 관리 서비스 실행.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$link.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f (Join-Path $PSScriptRoot 'start.ps1')
$link.WorkingDirectory = $PSScriptRoot
$link.Description = 'AI 모델 준비 후 두피 관리 웹을 자동으로 엽니다.'
$link.IconLocation = '{0},14' -f (Join-Path $env:SystemRoot 'System32\shell32.dll')
$link.Save()
Write-Output ('바탕화면 바로가기를 만들었습니다: {0}' -f $linkPath)

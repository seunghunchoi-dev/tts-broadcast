# 폐쇄망 설치 (폐쇄망_설치.bat 에서 실행) - 인터넷 연결 없이 offline_wheels 폴더에서 설치
# 한글 안내가 깨지지 않도록 배치 파일 대신 이 스크립트(UTF-8 BOM)에서 출력합니다.
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$host.UI.RawUI.WindowTitle = 'TTS 방송 - 폐쇄망 설치'

Write-Host '[TTS 방송] 폐쇄망 설치 - 인터넷 연결 없이 offline_wheels 폴더에서 설치합니다.'
Write-Host ''

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host 'Python 이 설치되어 있지 않습니다.' -ForegroundColor Red
    Write-Host 'offline_wheels\python-3.11.9-amd64.exe 를 먼저 설치하세요. ("Add python.exe to PATH" 체크)'
    exit 1
}
Write-Host ('Python: ' + (& python --version))

& python -m pip install --no-index --find-links offline_wheels -r requirements-offline.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '설치 실패: Python 버전이 3.11 인지 확인하세요. (offline_wheels 는 Python 3.11 64bit 용)' -ForegroundColor Red
    exit 1
}
Write-Host ''
Write-Host '설치 완료. 방송프로그램_실행.bat 으로 실행하세요.' -ForegroundColor Green

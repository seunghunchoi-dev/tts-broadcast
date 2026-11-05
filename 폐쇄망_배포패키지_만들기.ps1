# 폐쇄망 반입용 배포 패키지 생성
#   기본       : 프로그램 폴더를 zip 으로 묶음 (반입 PC 에 Python 3.9+ 필요)
#   -BuildExe  : PyInstaller 로 Python 없이 실행되는 exe 폴더 생성
#                (인터넷 되는 PC 에서 'pip install pyinstaller' 후 실행)
param([switch]$BuildExe)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $root 'dist'
$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
New-Item -ItemType Directory -Force $dist | Out-Null

$stage = Join-Path $env:TEMP "tts_broadcast_$stamp"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

$exclude = @('dist', 'build', 'build_nuitka', 'cache', 'logs', 'backups', '__pycache__', '.git', '.gitignore', '.gitattributes', '.claude',
             'config.json', 'nuitka-crash-report.xml', '비교샘플')
Get-ChildItem $root -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
    Copy-Item $_.FullName -Destination $stage -Recurse -Force
}
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
foreach ($sub in @('inbox\done', 'inbox\error')) {
    $p = Join-Path $stage $sub
    if (Test-Path $p) { Get-ChildItem $p | Remove-Item -Force }
}

if ($BuildExe) {
    Push-Location $stage
    try {
        python -m PyInstaller --noconfirm --windowed --name TTS방송 `
            --add-data "tts_broadcast\engines\_sapi_worker.ps1;tts_broadcast\engines" `
            --collect-all supertonic --collect-all onnxruntime main.py
        $app = Join-Path $stage 'dist\TTS방송'
        foreach ($f in @('schedules.json', 'templates.json', 'README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', 'LICENSE-EULA.txt',
                         'licenses', 'docs', 'assets', 'plugins', 'inbox', 'models', 'tools')) {
            if (Test-Path (Join-Path $stage $f)) { Copy-Item (Join-Path $stage $f) $app -Recurse -Force }
        }
        $zip = Join-Path $dist "TTS방송_exe_$stamp.zip"
        Compress-Archive -Path "$app\*" -DestinationPath $zip -Force
    }
    finally { Pop-Location }
}
else {
    $zip = Join-Path $dist "TTS방송_$stamp.zip"
    Compress-Archive -Path "$stage\*" -DestinationPath $zip -Force
}
Remove-Item -Recurse -Force $stage
Write-Host "생성 완료: $zip"

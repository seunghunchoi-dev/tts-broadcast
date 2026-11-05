# ============================================================================
#  TTS 방송 송출 시스템 - 보호 빌드 스크립트 (Nuitka)
#  Copyright (c) 2026 최승훈. All rights reserved.
#
#  본인 작성 코드(main.py, tts_broadcast)를 기계어로 컴파일하여 역설계를
#  어렵게 만든다. Qt(PySide6, LGPL)와 onnxruntime 등은 별도 파일로 동적
#  링크되어 라이선스를 준수한다. 모델/설정/자산은 exe 옆에 그대로 동봉한다.
#
#  사용: 인터넷 되는 PC 에서
#     powershell -ExecutionPolicy Bypass -File 빌드_exe_보호.ps1
# ============================================================================
$ErrorActionPreference = 'Stop'
$root  = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$outDir   = Join-Path $root 'build_nuitka'
$distDir  = Join-Path $outDir 'main.dist'
$stamp    = Get-Date -Format 'yyyyMMdd_HHmm'
$exeName  = 'TTS방송.exe'

Write-Host "`n[1/4] Nuitka 컴파일 시작 (10~30분 소요, 최초 1회 MinGW 자동 다운로드)..." -ForegroundColor Cyan

$nuitkaArgs = @(
    '-m', 'nuitka',
    '--standalone',
    '--windows-icon-from-ico=icon.ico',
    '--assume-yes-for-downloads',
    '--experimental=force-dependencies-pefile',
    '--enable-plugin=pyside6',
    '--enable-plugin=tk-inter',
    '--include-package=tts_broadcast',
    '--include-package=supertonic',
    '--include-package-data=onnxruntime',
    '--include-package-data=supertonic',
    '--include-data-files=tts_broadcast\engines\_sapi_worker.ps1=tts_broadcast\engines\_sapi_worker.ps1',
    '--windows-console-mode=disable',
    '--company-name=최승훈',
    '--product-name=TTS 방송 송출 시스템',
    '--file-description=TTS 자동 방송 송출 시스템',
    '--file-version=1.0.0.0',
    '--product-version=1.0.0.0',
    '--copyright=Copyright (c) 2026 최승훈 (Choi Seung-hun). All rights reserved.',
    "--output-dir=$outDir",
    "--output-filename=$exeName",
    '--remove-output',
    'main.py'
)

& python @nuitkaArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka 컴파일 실패 (exit $LASTEXITCODE)" }

if (-not (Test-Path (Join-Path $distDir $exeName))) {
    throw "컴파일 결과 exe 를 찾을 수 없음: $distDir\$exeName"
}

Write-Host "`n[2/4] 실행에 필요한 데이터/모델/라이선스 동봉..." -ForegroundColor Cyan
# 컴파일되지 않고 런타임에 파일로 읽히는 것들 (exe 옆에 그대로 둔다)
# config.json 은 넣지 않는다: 개발 PC의 라이선스 동의 기록이 고객에게 넘어가면 첫 실행 동의 창이 뜨지 않는다
$payload = @('schedules.json','templates.json',
             'README.md','THIRD_PARTY_NOTICES.md','LICENSE','LICENSE-EULA.txt',
             'licenses','docs','assets','plugins','inbox','models','tools')
foreach ($f in $payload) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        Copy-Item $src -Destination $distDir -Recurse -Force
        Write-Host "    + $f"
    }
}
# 감시 폴더는 비운 채로 포함
foreach ($sub in @('inbox\done','inbox\error')) {
    $p = Join-Path $distDir $sub
    if (Test-Path $p) { Get-ChildItem $p -File | Remove-Item -Force -ErrorAction SilentlyContinue }
}

Write-Host "`n[3/4] 배포 폴더 정리..." -ForegroundColor Cyan
# 이전 시험 실행에서 생긴 설정·기록을 배포본에 남기지 않는다
foreach ($f in @('config.json','logs','cache','backups')) {
    $p = Join-Path $distDir $f
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
$release = Join-Path $root "dist\TTS방송_보호_$stamp"
New-Item -ItemType Directory -Force (Split-Path $release) | Out-Null
if (Test-Path $release) { Remove-Item -Recurse -Force $release }
Copy-Item $distDir -Destination $release -Recurse -Force

Write-Host "`n[4/4] 압축..." -ForegroundColor Cyan
$zip = "$release.zip"
Compress-Archive -Path "$release\*" -DestinationPath $zip -Force

Write-Host "`n완료!" -ForegroundColor Green
Write-Host "  실행 파일 : $release\$exeName"
Write-Host "  배포 zip  : $zip"
Write-Host "  (이 폴더째 어느 PC 에나 복사하면 Python 설치 없이 실행됩니다)"

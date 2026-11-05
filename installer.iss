; ============================================================================
;  TTS 방송 송출 시스템 - 설치 프로그램 스크립트 (Inno Setup)
;  Copyright (c) 2026 최승훈 (Choi Seung-hun). All rights reserved.
;
;  빌드: ISCC.exe installer.iss (Inno Setup 6)
;  ※ 관리자 권한 없이 사용자 폴더(%LOCALAPPDATA%\Programs)에 설치됩니다.
;    이 앱은 config/logs/cache 를 자기 폴더에 쓰므로 쓰기 가능한 위치에 설치해야 합니다.
; ============================================================================

#define MyAppName "TTS 방송 송출 시스템"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "최승훈"
#define MyAppExeName "TTS방송.exe"
#define MySource "dist\TTS방송_보호_20261101_1550"

[Setup]
AppId={{B7E1B2C3-4D5E-6F70-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppContact=gwchoi96@gmail.com
AppCopyright=Copyright (c) 2026 최승훈 (Choi Seung-hun). All rights reserved.
DefaultDirName={autopf}\TTS방송
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
LicenseFile={#MySource}\LICENSE-EULA.txt
OutputDir=dist
OutputBaseFilename=TTS방송_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySource}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설치 시 포함된 파일 외에 실행 중 생성되는 캐시/로그는 제거 시 함께 정리
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"

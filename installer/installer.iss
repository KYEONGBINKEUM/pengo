; PSD Publisher 설치 프로그램 스크립트 (Inno Setup 6)
; 빌드: build-all.cmd 가 /DAppVersion=... /DStageDir=... 를 넘겨서 컴파일합니다.
#define AppName "Pengo"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\dist-installer\app"
#endif

[Setup]
; AppId 는 바꾸지 마세요: 같은 값이어야 새 setup.exe 를 실행했을 때 기존 설치를 덮어써서 업그레이드합니다.
AppId={{B7F3A0C2-5D1E-4C9B-9A57-6E2F1D4B8A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Pengo
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=.
OutputBaseFilename=PSD-Publisher-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\psd-publisher.exe
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; 이름이 PSD Publisher 이던 때의 옛 바로가기 정리 (시작 메뉴에 같은 앱이 두 개 보이지 않게)
Type: files; Name: "{autoprograms}\PSD Publisher.lnk"
Type: files; Name: "{autodesktop}\PSD Publisher.lnk"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\psd-publisher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\psd-publisher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
; 윈도우 아이콘 캐시를 새로 고쳐 시작 화면에 새 아이콘이 바로 보이게 한다
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden skipifdoesntexist
Filename: "{app}\psd-publisher.exe"; Description: "Pengo 실행"; Flags: nowait postinstall skipifsilent
; 앱 안에서 업데이트(/SILENT)한 경우: 설치가 끝나면 앱을 자동으로 다시 실행
Filename: "{app}\psd-publisher.exe"; Flags: nowait; Check: WizardSilent

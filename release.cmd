@echo off
rem ============================================================
rem  새 버전을 GitHub 에 올립니다 (배포 전용 공개 저장소: KYEONGBINKEUM/pengo)
rem  순서: 1) gui-rust\Cargo.toml 의 version 올리기  2) build-all.cmd 실행  3) 이 파일 실행
rem  올리고 나면 설치된 프로그램들이 다음 실행 때 "새 버전이 있어요" 알림을 받습니다.
rem  릴리스 설명은 RELEASE_NOTES.txt 가 있으면 그 내용을 쓰고, 없으면 기본 문구를 씁니다.
rem  (처음 한 번 gh auth login -h github.com 으로 로그인해 두어야 합니다)
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set REPO=KYEONGBINKEUM/pengo

for /f "tokens=3 delims= " %%v in ('findstr /b /c:"version = " gui-rust\Cargo.toml') do set VERSION=%%~v
set EXE=installer\PSD-Publisher-Setup-%VERSION%.exe

if not exist "%EXE%" (
  echo 설치 파일이 없습니다: %EXE%
  echo 먼저 build-all.cmd 를 실행하세요. ^(Cargo.toml 의 version 을 올렸는지도 확인하세요^)
  exit /b 1
)

echo 올릴 버전: v%VERSION%  ^(%REPO%^)
if exist RELEASE_NOTES.txt (
  gh release create v%VERSION% "%EXE%" "%EXE%.sha256" --repo %REPO% --title "Pengo %VERSION%" --notes-file RELEASE_NOTES.txt
) else (
  gh release create v%VERSION% "%EXE%" "%EXE%.sha256" --repo %REPO% --title "Pengo %VERSION%" --notes "Pengo %VERSION%"
)
if errorlevel 1 (
  echo.
  echo 올리지 못했습니다. 이미 같은 버전이 있거나 로그인이 필요할 수 있습니다.
  exit /b 1
)
echo.
echo 완료: https://github.com/%REPO%/releases/tag/v%VERSION%
exit /b 0

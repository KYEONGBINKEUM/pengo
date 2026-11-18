@echo off
rem ============================================================
rem  PSD Publisher 전체 빌드: 엔진(PyInstaller) -> 화면(Rust) -> 조립 -> 설치 프로그램(setup.exe)
rem  사용법: 이 파일을 더블클릭하거나  build-all.cmd  실행
rem  버전은 gui-rust\Cargo.toml 의 version 값을 올리면 됩니다 (예: 1.0.1)
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

for /f "tokens=3 delims= " %%v in ('findstr /b /c:"version = " gui-rust\Cargo.toml') do set VERSION=%%~v
echo [버전] %VERSION%

echo.
echo [1/4] 변환 엔진 묶는 중 (PyInstaller)...
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onedir --console --name publisher-engine ^
  --add-data "templates;templates" --add-data "company-rules.json;." ^
  --hidden-import semantic --hidden-import mismatch --collect-all psd_tools --collect-all tinycss2 publisher.py >build-engine.log 2>&1
if errorlevel 1 goto fail

echo [2/4] 화면 프로그램 빌드 중 (Rust)...
pushd gui-rust
cargo build --release
if errorlevel 1 (popd & goto fail)
popd

echo [3/4] 설치 파일 재료 모으는 중...
if exist dist-installer rmdir /s /q dist-installer
mkdir dist-installer\app
copy /y gui-rust\target\release\psd-publisher.exe dist-installer\app\psd-publisher.exe >nul
xcopy /e /i /q /y dist\publisher-engine dist-installer\app\engine >nul
copy /y assets\app.ico dist-installer\app\app.ico >nul
copy /y LICENSE dist-installer\app\LICENSE.txt >nul
copy /y THIRD-PARTY-NOTICES.txt dist-installer\app\THIRD-PARTY-NOTICES.txt >nul
if errorlevel 1 goto fail

echo [4/4] 설치 프로그램 만드는 중 (Inno Setup)...
tools\InnoSetup\ISCC.exe /Qp "/DAppVersion=%VERSION%" "/DStageDir=%~dp0dist-installer\app" installer\installer.iss
if errorlevel 1 goto fail

rem 업데이트 검증용 체크섬 파일 (릴리스에 setup.exe 와 함께 올립니다)
powershell -NoProfile -Command "$f='installer\PSD-Publisher-Setup-%VERSION%.exe'; ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() + '  ' + (Split-Path $f -Leaf)) | Set-Content -Encoding ascii ($f + '.sha256')"
echo.
echo 완료: installer\PSD-Publisher-Setup-%VERSION%.exe
exit /b 0

:fail
echo.
echo 빌드에 실패했습니다. build-engine.log 또는 위 메시지를 확인하세요.
exit /b 1

@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/2] 가상 환경을 준비합니다.
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -c "import sys" > nul 2>&1
  if errorlevel 1 (
    echo 기존 Python 환경의 경로가 바뀌어 다시 준비합니다.
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
echo [2/2] 필요한 구성요소를 설치합니다.
.venv\Scripts\python.exe -m pip install --no-index --find-links=offline_packages -r requirements.txt
if errorlevel 1 (
  echo.
  echo 오프라인 설치 파일을 찾지 못했습니다.
  echo 인터넷이 연결된 PC에서 prepare_offline.bat를 먼저 실행해 주세요.
  pause
  exit /b 1
)
echo 설치가 완료되었습니다. run.bat를 실행하세요.
pause

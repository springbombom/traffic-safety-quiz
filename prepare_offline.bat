@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist offline_packages mkdir offline_packages
py -3 -m pip download -r requirements.txt -d offline_packages
echo 다운로드가 완료되었습니다. 이 폴더 전체를 교육장 PC로 복사하세요.
pause

@echo off
setlocal
pushd "%~dp0.."

python -m pip install -r src\requirements.txt
if errorlevel 1 goto :failed

python -m PyInstaller --onefile --console --name run --clean --noconfirm src\anki_deck.py
if errorlevel 1 goto :failed

copy /Y dist\run.exe run.exe
if errorlevel 1 goto :failed

echo Built run.exe successfully.
popd
exit /b 0

:failed
echo Build failed. Check the error above.
popd
exit /b 1

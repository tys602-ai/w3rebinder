@echo off
rem Builds dist\W3KeyBinder.exe (needs Python 3.9+ from python.org)
python -m pip install --upgrade pyinstaller || goto :err
python -m PyInstaller --noconfirm --onefile --windowed --name W3KeyBinder --icon w3keybinder\assets\icon.ico --add-data "w3keybinder/sv_ttk;w3keybinder/sv_ttk" --add-data "w3keybinder/assets;w3keybinder/assets" W3KeyBinder.pyw || goto :err
echo.
echo Done: dist\W3KeyBinder.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1

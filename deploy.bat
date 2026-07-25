@echo off
cd /d "%~dp0"
echo.
echo ========================================
echo   SMARTBOT - Railway Deploy
echo ========================================
echo.

REM Degisiklik var mi kontrol et
git status --porcelain > "%TEMP%\git_status.txt" 2>&1
for %%A in ("%TEMP%\git_status.txt") do set STATUS_SIZE=%%~zA
del "%TEMP%\git_status.txt" 2>nul

if %STATUS_SIZE% EQU 0 (
    echo Commit edilecek degisiklik yok.
    echo Direkt push yapiliyor...
    goto :push
)

set /p MSG="Commit mesaji yaz (Enter = 'update'): "
if "%MSG%"=="" set MSG=update

echo.
echo Dosyalar ekleniyor...
git add .

echo Commit atiliyor: %MSG%
git commit -m "%MSG%"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo HATA: Commit basarisiz!
    goto :end
)

:push
echo.
set RETRY=0

:push_retry
set /a RETRY+=1
echo Push deneme %RETRY%/3 ...
git push origin main 2>&1
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo   TAMAMLANDI - Railway deploy basliyor
    echo ========================================
    goto :end
)

if %RETRY% LSS 3 (
    echo Baglanti hatasi, 5 saniye sonra tekrar deneniyor...
    timeout /t 5 /nobreak >nul
    goto :push_retry
)

echo.
echo HATA: Push 3 denemede de basarisiz!
echo Yukaridaki hata mesajini kontrol edin.

:end
echo.
pause

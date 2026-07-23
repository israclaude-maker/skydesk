# ============================================
# SkyDesk - Full Deploy Script (LOCAL / Windows)
# Run this from: C:\Users\skypc\Desktop\skydesk
# ============================================

Write-Host "=== [1/3] Git commit + push ===" -ForegroundColor Cyan
git add .
git commit -m "update"
git push origin main

Write-Host "=== [2/3] Building EXE + Installer ===" -ForegroundColor Cyan
Set-Location "desktop_app"
.\build.bat
Set-Location ".."

Write-Host "=== [3/3] Uploading installer to VPS ===" -ForegroundColor Cyan
scp desktop_app\installer_output\SkyDeskSetup.exe root@76.13.219.77:/tmp/

Write-Host ""
Write-Host "Local part DONE." -ForegroundColor Green
Write-Host "Ab VPS par SSH karke deploy_vps.sh chalao (ya neeche wali 2 lines paste karo):" -ForegroundColor Yellow
Write-Host "mv /tmp/SkyDeskSetup.exe /var/www/skydesk/downloads/SkyDeskSetup.exe" -ForegroundColor Yellow
Write-Host "chmod 644 /var/www/skydesk/downloads/SkyDeskSetup.exe && systemctl restart skydesk" -ForegroundColor Yellow

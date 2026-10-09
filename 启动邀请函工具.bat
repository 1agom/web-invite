@echo off
chcp 65001 >nul
cd /d %~dp0
if "%INVITE_ADMIN_KEY%"=="" (
  echo 请先在当前终端设置 INVITE_ADMIN_KEY。
  echo 示例仅作格式参考，勿使用示例值作为真实密钥。
  echo   set INVITE_ADMIN_KEY=replace-with-a-long-random-secret
  pause
  exit /b 1
)
if "%INVITE_PAGE_PASSWORD%"=="" (
  echo 请先在当前终端设置 INVITE_PAGE_PASSWORD。
  echo 示例仅作格式参考，勿使用示例值作为真实密码。
  echo   set INVITE_PAGE_PASSWORD=replace-with-a-private-password
  pause
  exit /b 1
)
python server.py
pause

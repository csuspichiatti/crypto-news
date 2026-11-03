@echo off
chcp 65001 >nul
cd /d "%~dp0"
title News Agent v1
echo.
echo ════════════════════════════════════════════════
echo   News Agent v1 — BTC + Pi Network
echo ════════════════════════════════════════════════
echo.
python news_agent_v1.py
pause

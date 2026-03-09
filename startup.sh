#!/bin/bash
# FY114 藥物辨識子系統 — 開機自動啟動腳本
# 設定方式：chmod +x startup.sh && crontab -e 加入：
#   @reboot /home/admin/Desktop/FY114-Drug-Recognition-Subsystem/startup.sh

LOG="/tmp/fy114_startup.log"

echo "$(date): Startup script started" >> "$LOG"

# 等待顯示環境就緒
sleep 5

# 旋轉螢幕（依實際螢幕輸出名稱調整）
echo "$(date): Rotating screen" >> "$LOG"
DISPLAY=:0 xrandr --output XWAYLAND0 --rotate right 2>> "$LOG" || true

# 進入專案資料夾
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "$(date): Starting app from $PROJECT_DIR" >> "$LOG"
cd "$PROJECT_DIR"

# 啟動虛擬環境並執行
source .venv/bin/activate
python run.py --fullscreen 2>&1 | tee -a "$LOG"

#!/bin/bash
# Drug-Recognition-Subsystem — 開機自動啟動腳本
#
# 設定方式：
#   chmod +x startup.sh
#   crontab -e
#   加入：@reboot /完整路徑/Drug-Recognition-Subsystem/startup.sh
#
# 注意：eth0 靜態 IP（192.168.50.2）請透過 /etc/dhcpcd.conf 設定，
#       勿在此腳本用 ifconfig 設定（crontab 無 root 權限，且執行時機過早）。
export DISPLAY=:0
export XAUTHORITY=/home/admin/.Xauthority

LOG="/tmp/drug_recognition_startup.log"
echo "$(date): Startup script started" >> "$LOG"

# 等待顯示環境就緒
sleep 5

# 等待 eth0 取得 IP（最多等 30 秒）
echo "$(date): Waiting for eth0..." >> "$LOG"
for i in $(seq 1 15); do
    ip addr show eth0 | grep -q "192.168.50.2" && break
    sleep 2
done
echo "$(date): eth0 status: $(ip addr show eth0 | grep 'inet ')" >> "$LOG"

# 旋轉螢幕（依實際螢幕輸出名稱調整）
DISPLAY=:0 xrandr --output XWAYLAND0 --rotate right 2>> "$LOG" || true

# 進入專案資料夾
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "$(date): Starting app from $PROJECT_DIR" >> "$LOG"
cd "$PROJECT_DIR"

# 啟動虛擬環境
source .venv/bin/activate

# 啟動 GUI（前景執行，此行結束 = 使用者關閉視窗）
# 連線設定請修改 api.yaml
echo "$(date): Starting run.py" >> "$LOG"
python run.py --fullscreen 2>&1 | tee -a "$LOG"


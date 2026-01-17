#!/bin/bash
#
# start_printer_simple.sh
# 簡化版啟動腳本 - 使用 bluetoothctl 設定
#
# 使用方法:
#   sudo ./start_printer_simple.sh
#

set -e

echo "========================================"
echo "BLE Printer Emulator - Simple Start"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 停止所有現有服務
echo "[1/5] Stopping bluetooth..."
systemctl stop bluetooth 2>/dev/null || true
killall bluetoothd 2>/dev/null || true
sleep 1

# 解除封鎖並啟動
echo "[2/5] Starting bluetooth service..."
rfkill unblock bluetooth 2>/dev/null || true
systemctl start bluetooth
sleep 2

# 使用 bluetoothctl 設定
echo "[3/5] Configuring with bluetoothctl..."
bluetoothctl << EOF
power on
agent NoInputNoOutput
default-agent
discoverable on
pairable on
EOF

# btmgmt 額外設定
echo "[4/5] Additional btmgmt settings..."
btmgmt bondable off 2>/dev/null || true
btmgmt sc off 2>/dev/null || true
btmgmt io-cap 3 2>/dev/null || true

echo ""
echo "Current settings:"
btmgmt info | grep -E "current settings|name"
echo ""

# 啟動模擬器
echo "[5/5] Starting emulator..."
echo "========================================"
echo ""

cd "$SCRIPT_DIR"
python3 main_hci_v3.py

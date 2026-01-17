#!/bin/bash
#
# start_printer_v5.sh
# 解決 SMP Security Request 問題
#
# 關鍵改進:
# 1. 使用 -P 選項只載入必要的 plugin
# 2. 禁用 SSP (Secure Simple Pairing)
# 3. 確保 bluetoothd 完全停止後再重啟
#

set -e

echo "========================================"
echo "BLE Printer Emulator v5"
echo "Minimal Plugin Mode"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. 完全停止所有藍牙進程
echo "[1/7] Killing all bluetooth processes..."
systemctl stop bluetooth 2>/dev/null || true
sleep 1
pkill -9 bluetoothd 2>/dev/null || true
pkill -9 -f "bluetooth" 2>/dev/null || true
sleep 2

# 確認沒有殘留進程
if pgrep -x bluetoothd > /dev/null; then
    echo "ERROR: bluetoothd still running!"
    pkill -9 bluetoothd
    sleep 1
fi

# 2. 解除 RF-kill 封鎖
echo "[2/7] Unblocking bluetooth..."
rfkill unblock bluetooth 2>/dev/null || true

# 3. 重置 HCI
echo "[3/7] Resetting HCI adapter..."
hciconfig hci0 down 2>/dev/null || true
sleep 1
hciconfig hci0 up 2>/dev/null || true
sleep 1

# 4. 手動啟動 bluetoothd - 使用 -P 只載入 gatt plugin
echo "[4/7] Starting bluetoothd with minimal plugins..."
# -P hostname: 只載入 hostname plugin (最小化)
# --noplugin=*: 禁用所有其他 plugin
# -E: 啟用實驗功能

/usr/libexec/bluetooth/bluetoothd -E -P hostname &
BLUETOOTHD_PID=$!
echo "  bluetoothd started (PID: $BLUETOOTHD_PID)"
sleep 3

# 確認 bluetoothd 正在運行
if ! kill -0 $BLUETOOTHD_PID 2>/dev/null; then
    echo "ERROR: bluetoothd failed to start!"
    echo "Trying alternative method..."
    /usr/libexec/bluetooth/bluetoothd &
    BLUETOOTHD_PID=$!
    sleep 3
fi

# 5. 使用 btmgmt 設定關鍵選項
echo "[5/7] Configuring with btmgmt..."
btmgmt power on
btmgmt name "BT-B36"

# 關鍵設定 - 禁用配對相關功能
btmgmt bondable off      # 禁止配對
btmgmt ssp off           # 禁用 Secure Simple Pairing (關鍵!)
btmgmt sc off            # 禁用 Secure Connections
btmgmt io-cap 3          # NoInputNoOutput

# 啟用可發現和連接
btmgmt discov on
btmgmt connectable on
btmgmt le on
btmgmt advertising on

# 6. 顯示當前設定
echo ""
echo "[6/7] Current settings:"
btmgmt info 2>&1 | head -15
echo ""

# 檢查設定
SETTINGS=$(btmgmt info 2>&1 | grep "current settings" || echo "")
echo "Checking critical settings..."

if echo "$SETTINGS" | grep -q "bondable"; then
    echo "  [WARN] Bondable is enabled"
else
    echo "  [OK] Bondable is disabled"
fi

if echo "$SETTINGS" | grep -q "ssp"; then
    echo "  [WARN] SSP may be enabled"
else
    echo "  [OK] SSP is disabled"
fi

if echo "$SETTINGS" | grep -q "secure-conn"; then
    echo "  [WARN] Secure Connections may be enabled"
else
    echo "  [OK] Secure Connections is disabled"
fi

echo ""

# 7. 啟動模擬器
echo "[7/7] Starting emulator..."
echo "========================================"
echo ""

cd "$SCRIPT_DIR"

# 捕獲信號以便清理
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BLUETOOTHD_PID 2>/dev/null || true
    systemctl start bluetooth 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

python3 main_hci_v3.py

# 清理
cleanup

#!/bin/bash
#
# start_printer_v4.sh
# 完整解決配對問題的啟動腳本
#
# 關鍵改進:
# 1. 停用所有需要認證的 BlueZ plugin (mcp, vcp, bap, csip, avrcp, midi)
# 2. 使用 btmgmt 強制禁用 Secure Connections 和 Bondable
# 3. 手動啟動 bluetoothd 而非使用 systemctl
#
# 使用方法:
#   sudo ./start_printer_v4.sh
#

set -e

echo "========================================"
echo "BLE Printer Emulator v4"
echo "Complete No-Pairing Solution"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. 停止所有現有藍牙服務
echo "[1/6] Stopping all bluetooth processes..."
systemctl stop bluetooth 2>/dev/null || true
killall bluetoothd 2>/dev/null || true
sleep 1

# 2. 解除 RF-kill 封鎖
echo "[2/6] Unblocking bluetooth..."
rfkill unblock bluetooth 2>/dev/null || true
sleep 1

# 3. 手動啟動 bluetoothd，停用所有需要認證的 plugin
echo "[3/6] Starting bluetoothd with disabled plugins..."
# 停用的 plugin:
#   - sap: SIM Access Profile
#   - input: HID input devices
#   - mcp: Media Control Profile (造成 Insufficient Authentication)
#   - vcp: Volume Control Profile (造成 Insufficient Authentication)
#   - bap: Broadcast Audio Profile
#   - csip: Coordinated Set Identification Profile
#   - avrcp: Audio/Video Remote Control Profile
#   - midi: MIDI over BLE
#   - bass: Broadcast Audio Scan Service

/usr/libexec/bluetooth/bluetoothd --noplugin=sap,input,mcp,vcp,bap,csip,avrcp,midi,bass &
BLUETOOTHD_PID=$!
echo "  bluetoothd started (PID: $BLUETOOTHD_PID)"
sleep 2

# 4. 使用 btmgmt 設定關鍵選項
echo "[4/6] Configuring with btmgmt..."
btmgmt power on
btmgmt name "BT-B36"
btmgmt bondable off      # 禁止配對
btmgmt sc off            # 禁用 Secure Connections
btmgmt io-cap 3          # NoInputNoOutput
btmgmt discov on         # 可被發現
btmgmt connectable on    # 可連接
btmgmt advertising on    # 啟用廣播

# 5. 顯示當前設定
echo ""
echo "[5/6] Current settings:"
btmgmt info | head -20
echo ""

# 確認關鍵設定
SETTINGS=$(btmgmt info | grep "current settings")
if echo "$SETTINGS" | grep -q "bondable"; then
    echo "WARNING: Bondable is still enabled!"
else
    echo "OK: Bondable is disabled"
fi

if echo "$SETTINGS" | grep -q "sc"; then
    echo "WARNING: Secure Connections may still be enabled!"
else
    echo "OK: Secure Connections is disabled"
fi
echo ""

# 6. 啟動模擬器
echo "[6/6] Starting emulator..."
echo "========================================"
echo ""

cd "$SCRIPT_DIR"

# 捕獲 SIGINT/SIGTERM 以便清理
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BLUETOOTHD_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

python3 main_hci_v3.py

# 清理
kill $BLUETOOTHD_PID 2>/dev/null || true

#!/bin/bash
#
# start_printer_v7.sh - 禁用 SMP 的嘗試
#
# 這個版本嘗試通過設定 adapter 來避免 Security Request
#

set -e

echo "========================================"
echo "BLE Printer Emulator v7"
echo "Attempt to disable SMP completely"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. 完全停止所有藍牙進程
echo "[1/7] Stopping all bluetooth processes..."
systemctl stop bluetooth 2>/dev/null || true
sleep 1
pkill -9 bluetoothd 2>/dev/null || true
sleep 2

while pgrep -x bluetoothd > /dev/null; do
    pkill -9 bluetoothd 2>/dev/null || true
    sleep 1
done
echo "  Done"

# 2. 解除 RF-kill 封鎖
echo "[2/7] Unblocking bluetooth..."
rfkill unblock bluetooth 2>/dev/null || true

# 3. 重置 HCI
echo "[3/7] Resetting HCI adapter..."
hciconfig hci0 down 2>/dev/null || true
sleep 1
hciconfig hci0 up 2>/dev/null || true
sleep 1

# 4. 使用 btmgmt 在 bluetoothd 啟動前設定
echo "[4/7] Pre-configuring with btmgmt..."
btmgmt power off 2>/dev/null || true
sleep 1
btmgmt le on 2>/dev/null || true
btmgmt bredr off 2>/dev/null || true
btmgmt bondable off 2>/dev/null || true
btmgmt ssp off 2>/dev/null || true
btmgmt sc off 2>/dev/null || true
btmgmt io-cap 3 2>/dev/null || true

# 5. 啟動 bluetoothd 但不自動配對
echo "[5/7] Starting bluetoothd..."
# 使用 compat 選項和禁用插件
/usr/libexec/bluetooth/bluetoothd -E -C &
BLUETOOTHD_PID=$!
echo "  bluetoothd started (PID: $BLUETOOTHD_PID)"
sleep 3

if ! kill -0 $BLUETOOTHD_PID 2>/dev/null; then
    echo "ERROR: bluetoothd failed to start!"
    exit 1
fi

# 6. 再次設定並使用 bluetoothctl 進行額外配置
echo "[6/7] Post-configuring..."
btmgmt power on
btmgmt name "BT-B36"
btmgmt bondable off
btmgmt sc off
btmgmt io-cap 3
btmgmt discov on
btmgmt connectable on
btmgmt advertising on

# 使用 bluetoothctl 設定額外選項
bluetoothctl << 'EOF'
power on
agent off
discoverable on
pairable off
EOF

# 7. 顯示當前設定
echo ""
echo "[7/7] Current settings:"
btmgmt info 2>&1 | grep -E "name|current settings" | head -3
echo ""

SETTINGS=$(btmgmt info 2>&1 | grep "current settings" || echo "")
echo "Checking settings..."
if echo "$SETTINGS" | grep -qw "bondable"; then
    echo "  [WARN] Bondable is enabled"
else
    echo "  [OK] Bondable is disabled"
fi
echo ""

# 啟動模擬器
echo "Starting emulator..."
echo "========================================"
echo ""
echo "NOTE: If nRF Connect shows a pairing request, tap 'Pair' or 'OK'."
echo "      The pairing should complete automatically (Just Works)."
echo ""

cd "$SCRIPT_DIR"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BLUETOOTHD_PID 2>/dev/null || true
    systemctl start bluetooth 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

if [ -f "main_hci_v4.py" ]; then
    python3 main_hci_v4.py
else
    python3 main_hci_v3.py
fi

cleanup

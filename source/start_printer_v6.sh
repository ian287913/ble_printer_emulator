#!/bin/bash
#
# start_printer_v6.sh - 最終解決方案
#
# 問題：BlueZ 內建的 Audio 服務會觸發 SMP Security Request
# 解決：完全停用 bluetoothd 的 GATT client 功能
#

set -e

echo "========================================"
echo "BLE Printer Emulator v6"
echo "Final Solution - Disable GATT Client"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 0. 先更新 main.conf
echo "[0/8] Checking main.conf..."
if ! grep -q "Client = false" /etc/bluetooth/main.conf 2>/dev/null; then
    echo "  Updating /etc/bluetooth/main.conf..."

    # 備份原始檔案
    cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.backup 2>/dev/null || true

    # 確保 [GATT] 區段存在並添加 Client = false
    if grep -q "\[GATT\]" /etc/bluetooth/main.conf; then
        # 在 [GATT] 區段後添加 Client = false
        sed -i '/\[GATT\]/a Client = false' /etc/bluetooth/main.conf
    else
        # 添加 [GATT] 區段
        echo -e "\n[GATT]\nClient = false" >> /etc/bluetooth/main.conf
    fi

    # 確保 SecureConnections = off
    if ! grep -q "SecureConnections" /etc/bluetooth/main.conf; then
        sed -i '/\[General\]/a SecureConnections = off' /etc/bluetooth/main.conf
    fi

    echo "  main.conf updated"
else
    echo "  main.conf already configured"
fi

# 1. 完全停止所有藍牙進程
echo "[1/8] Stopping all bluetooth processes..."
systemctl stop bluetooth 2>/dev/null || true
sleep 1
pkill -9 bluetoothd 2>/dev/null || true
sleep 2

# 確認沒有殘留進程
while pgrep -x bluetoothd > /dev/null; do
    echo "  Waiting for bluetoothd to stop..."
    pkill -9 bluetoothd 2>/dev/null || true
    sleep 1
done
echo "  bluetoothd stopped"

# 2. 解除 RF-kill 封鎖
echo "[2/8] Unblocking bluetooth..."
rfkill unblock bluetooth 2>/dev/null || true

# 3. 重置 HCI
echo "[3/8] Resetting HCI adapter..."
hciconfig hci0 down 2>/dev/null || true
sleep 1
hciconfig hci0 up 2>/dev/null || true
sleep 1

# 4. 啟動 bluetoothd
echo "[4/8] Starting bluetoothd..."
# 使用配置檔而非命令行參數
/usr/libexec/bluetooth/bluetoothd -E &
BLUETOOTHD_PID=$!
echo "  bluetoothd started (PID: $BLUETOOTHD_PID)"
sleep 3

# 確認 bluetoothd 正在運行
if ! kill -0 $BLUETOOTHD_PID 2>/dev/null; then
    echo "ERROR: bluetoothd failed to start!"
    exit 1
fi

# 5. 使用 btmgmt 設定
echo "[5/8] Configuring with btmgmt..."
btmgmt power on 2>&1 | head -1
btmgmt name "BT-B36" 2>&1 | head -1
btmgmt bondable off 2>&1 | head -1
btmgmt ssp off 2>&1 | head -1
btmgmt sc off 2>&1 | head -1
btmgmt io-cap 3 2>&1 | head -1
btmgmt discov on 2>&1 | head -1
btmgmt connectable on 2>&1 | head -1
btmgmt le on 2>&1 | head -1
btmgmt advertising on 2>&1 | head -1

# 6. 刪除已配對的裝置（避免舊的安全設定影響）
echo "[6/8] Removing paired devices..."
# 列出所有已配對裝置並刪除
bluetoothctl paired-devices 2>/dev/null | while read -r line; do
    MAC=$(echo "$line" | awk '{print $2}')
    if [ -n "$MAC" ]; then
        echo "  Removing $MAC"
        bluetoothctl remove "$MAC" 2>/dev/null || true
    fi
done

# 7. 顯示當前設定
echo ""
echo "[7/8] Current settings:"
btmgmt info 2>&1 | grep -E "name|current settings" | head -3
echo ""

# 檢查關鍵設定
SETTINGS=$(btmgmt info 2>&1 | grep "current settings" || echo "")
echo "Checking critical settings..."

if echo "$SETTINGS" | grep -qw "bondable"; then
    echo "  [WARN] Bondable is enabled"
else
    echo "  [OK] Bondable is disabled"
fi

if echo "$SETTINGS" | grep -qw "ssp"; then
    echo "  [WARN] SSP is enabled"
else
    echo "  [OK] SSP is disabled"
fi

if echo "$SETTINGS" | grep -qw "secure-conn"; then
    echo "  [WARN] Secure Connections is enabled"
else
    echo "  [OK] Secure Connections is disabled"
fi

echo ""

# 8. 啟動模擬器
echo "[8/8] Starting emulator..."
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

# 使用新版本的 Python 程式
if [ -f "main_hci_v4.py" ]; then
    python3 main_hci_v4.py
else
    python3 main_hci_v3.py
fi

# 清理
cleanup

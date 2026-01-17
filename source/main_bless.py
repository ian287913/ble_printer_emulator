#!/usr/bin/env python3
"""
BLE Printer Emulator - 使用 bless 庫
完全繞過 bluetoothd 的 SMP Security Request

安裝:
    pip3 install bless

使用:
    sudo python3 main_bless.py

注意: 這個方法不使用 bluetoothd 的 GATT server，
而是直接使用 bless 庫來建立 GATT server。
"""

import asyncio
import sys
import os
import datetime
from typing import Any

try:
    from bless import BlessServer, BlessGATTCharacteristic, GATTCharacteristicProperties, GATTAttributePermissions
except ImportError:
    print("Error: bless library not found.")
    print("Install with: pip3 install bless")
    sys.exit(1)

# =============================================================================
# 設定
# =============================================================================
DEVICE_NAME = "BT-B36"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "printer_data.log")

# =============================================================================
# UUID 定義
# =============================================================================
# 主要列印服務
PRINT_SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
PRINT_WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
PRINT_NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

# Device Information Service
DEVICE_INFO_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"

# =============================================================================
# 日誌
# =============================================================================
def log(msg):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}")

def log_data(data: bytes, source: str):
    timestamp = datetime.datetime.now().isoformat()
    log(f"RECEIVED from {source}: {data.hex(' ')}")
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{timestamp}] {source}: {data.hex(' ')}\n")
    except:
        pass

# =============================================================================
# 指令處理
# =============================================================================
def process_command(data: bytes) -> bytes:
    if len(data) == 0:
        return None

    if len(data) >= 3 and data[0] == 0x10 and data[1] == 0x04:
        log(f"CMD: DLE EOT {data[2]} (Status query)")
        return bytes([0x16])

    if len(data) >= 3 and data[0] == 0x1D and data[1] == 0x72:
        log(f"CMD: GS r {data[2]} (Transmit status)")
        return bytes([0x00])

    if len(data) >= 3 and data[0] == 0x1D and data[1] == 0x49:
        log(f"CMD: GS I {data[2]} (Printer ID)")
        return b"BT-B36\x00"

    if len(data) >= 2 and data[0] == 0x1B and data[1] == 0x40:
        log(f"CMD: ESC @ (Initialize)")
        return None

    if data[0] == 0x05:
        log(f"CMD: ENQ (Enquiry)")
        return bytes([0x06])

    return None

# =============================================================================
# Callback 函數
# =============================================================================
server: BlessServer = None

def read_request(characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
    """處理讀取請求"""
    uuid = str(characteristic.uuid).lower()
    log(f"Read request: {uuid[-8:]}")

    if uuid == MANUFACTURER_NAME_UUID:
        return bytearray(b"Printer")
    elif uuid == MODEL_NUMBER_UUID:
        return bytearray(b"BT-B36")
    else:
        return bytearray(b"")

def write_request(characteristic: BlessGATTCharacteristic, value: Any, **kwargs):
    """處理寫入請求"""
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)
    log_data(data, uuid[-8:])

    response = process_command(data)
    if response and server:
        # 發送通知
        asyncio.create_task(send_notification(response))

async def send_notification(data: bytes):
    """發送通知"""
    global server
    if server:
        try:
            server.get_characteristic(PRINT_NOTIFY_UUID)
            server.update_value(PRINT_SERVICE_UUID, PRINT_NOTIFY_UUID, bytearray(data))
            log(f"Notification sent: {data.hex(' ')}")
        except Exception as e:
            log(f"Failed to send notification: {e}")

# =============================================================================
# 主程式
# =============================================================================
async def main():
    global server

    print(f"\n{'='*60}")
    print(f"BLE Printer Emulator - bless version")
    print(f"Device: {DEVICE_NAME}")
    print(f"{'='*60}\n")

    # 初始化日誌
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Session (bless): {datetime.datetime.now().isoformat()}\n")
            f.write(f"{'='*60}\n")
    except:
        pass

    # 建立 GATT Server
    log("Creating GATT server...")

    server = BlessServer(name=DEVICE_NAME)
    server.read_request_func = read_request
    server.write_request_func = write_request

    await server.add_new_service(PRINT_SERVICE_UUID)

    # 寫入 Characteristic
    await server.add_new_characteristic(
        PRINT_SERVICE_UUID,
        PRINT_WRITE_UUID,
        GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
        None,
        GATTAttributePermissions.writeable
    )

    # 通知 Characteristic
    await server.add_new_characteristic(
        PRINT_SERVICE_UUID,
        PRINT_NOTIFY_UUID,
        GATTCharacteristicProperties.notify,
        None,
        GATTAttributePermissions.readable
    )

    # Device Information Service
    await server.add_new_service(DEVICE_INFO_UUID)

    await server.add_new_characteristic(
        DEVICE_INFO_UUID,
        MANUFACTURER_NAME_UUID,
        GATTCharacteristicProperties.read,
        bytearray(b"Printer"),
        GATTAttributePermissions.readable
    )

    await server.add_new_characteristic(
        DEVICE_INFO_UUID,
        MODEL_NUMBER_UUID,
        GATTCharacteristicProperties.read,
        bytearray(b"BT-B36"),
        GATTAttributePermissions.readable
    )

    # 啟動廣播
    log("Starting advertising...")
    await server.start()

    log("")
    log("="*60)
    log(f'READY! "{DEVICE_NAME}" is advertising')
    log("="*60)
    log("")
    log("Services:")
    log(f"  - Print Service ({PRINT_SERVICE_UUID[-8:-4]})")
    log(f"  - Device Information ({DEVICE_INFO_UUID[-8:-4]})")
    log("")
    log("Waiting for connections...")
    log("")

    # 保持運行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        log("\nShutting down...")
    finally:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BLE peripheral emulator that makes a Raspberry Pi simulate a BT-B36 thermal printer. Clients (e.g. mobile apps) can connect via BLE and send print commands without pairing or encryption. The project language is Traditional Chinese (zh-TW).

Three main parts:
1. **BlueZ 5.82 source modifications** — patches to disable security/pairing in the Linux Bluetooth stack (documented in `bluez-modification-guide.md`)
2. **Python GATT server** (`code/test_gatt.py`) — registers a BLE GATT service via D-Bus that accepts write commands and supports notifications
3. **ESC/POS 解碼器** (`code/escpos_decoder.py`) — 狀態機式指令解碼器 + 智慧回覆產生器（詳見 `ESCPOS-guide.md`）

## Running the GATT Server

Target platform is Raspberry Pi OS. The script requires the modified BlueZ daemon to be running.

```bash
# Install Python dependencies
sudo apt install -y python3-dbus python3-gi

# Run the emulator (requires root for D-Bus system bus access)
python3 code/test_gatt.py
```

Verify with nRF Connect app on a mobile device: scan for "BT-B36", connect (no pairing prompt should appear), discover services, write to ff02, subscribe to ff01.

## Architecture

```
Modified BlueZ (bluetoothd 5.82, security disabled)
        │ D-Bus system bus
        ▼
Python GATT Server (test_gatt.py)
  ├── Application — ObjectManager, owns services
  ├── Advertisement — BLE advertising as "BT-B36"
  ├── PrinterService — GATT service UUID ff00
  │     ├── WriteCharacteristic (ff02) — receives print data → ESCPOSDecoder
  │     └── NotifyCharacteristic (ff01) — sends smart responses back
  ├── main() — sets up adapter, registers GATT app + advertisement, runs GLib loop
  │
  └── ESCPOSDecoder (escpos_decoder.py)
        ├── 狀態機解析器 — 處理跨 BLE 封包的指令邊界
        ├── 智慧回覆產生器 — 偵測查詢指令回傳正確狀態
        └── Log 記錄器 — logs/escpos_YYYYMMDD_HHMMSS.log
```

All D-Bus objects live under `/org/bluez/example/`. The adapter used is `hci0`.

## Key UUIDs

| Role | UUID |
|------|------|
| Service | `0000ff00-0000-1000-8000-00805f9b34fb` |
| Write (print data) | `0000ff02-0000-1000-8000-00805f9b34fb` |
| Notify (status) | `0000ff01-0000-1000-8000-00805f9b34fb` |

The real BT-B36 device exposes 7 services (see `printer_info.json`); only the primary print service (ff00) is emulated so far.

## ESC/POS 解碼器

`code/escpos_decoder.py` 實作完整的 ESC/POS 指令解碼與智慧回覆功能。詳細技術文件請參考 `ESCPOS-guide.md`。

**核心流程：**
1. `PrintWriteCharacteristic.WriteValue()` 收到 BLE 寫入資料
2. 資料送入 `ESCPOSDecoder.feed(data)` 解碼
3. 回傳 `(commands, responses)` — commands 記錄到 log，responses 透過 ff01 notify 回傳
4. 狀態查詢指令（DLE EOT, GS I, GS r）會產生對應的智慧回覆；其他指令回傳標準 ACK (`0x00`)

**Log 位置：** `logs/escpos_YYYYMMDD_HHMMSS.log`（自動建立，同時輸出到終端）

## BlueZ Modifications

Five patches applied to BlueZ 5.82 source (see `bluez-modification-guide.md` for details):

1. `src/shared/att.c` — `bt_att_set_security()` returns true immediately (skip security)
2. `src/shared/gatt-server.c` — `check_permissions()` returns 0 (allow all access)
3. `src/adapter.c` — IO Capability set to `NoInputNoOutput` (0x03)
4. `src/adapter.c` — `MGMT_SETTING_SECURE_CONN` commented out (disable Secure Connections)
5. `src/shared/att.c` — `chan->sec_level = BT_ATT_SECURITY_LOW` in `bt_att_new()`

Build modified BlueZ:
```bash
cd ~/bluez-5.82
./configure --prefix=/usr --mandir=/usr/share/man \
    --sysconfdir=/etc --localstatedir=/var \
    --enable-experimental --enable-deprecated \
    --with-udevdir=/lib/udev \
    --with-systemdsystemunitdir=/lib/systemd/system \
    --with-systemduserunitdir=/usr/lib/systemd/user
make -j4
sudo make install
sudo systemctl daemon-reload && sudo systemctl restart bluetooth
```

## Known Gotchas

- `sec_level` is a member of `struct bt_att_chan`, not `struct bt_att` — use `chan->sec_level`
- `configure` on Raspberry Pi OS requires `--with-udevdir` and `--with-systemd*` flags or it errors
- The `Application` class must implement `GetManagedObjects` or GATT registration fails with "No object received"
- BlueZ config at `/etc/bluetooth/main.conf` must set `Name = BT-B36` and `DiscoverableTimeout = 0`

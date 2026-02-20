# BlueZ 原始碼修改指引：模擬 BT-B36 熱感印表機

本指引說明如何修改 BlueZ 原始碼，讓 Raspberry Pi 完全模擬 BT-B36 熱感印表機的 BLE 行為。

## 目錄

1. [修改項目總覽](#1-修改項目總覽)
2. [準備工作環境](#2-準備工作環境)
3. [修改原始碼](#3-修改原始碼)
4. [編譯安裝](#4-編譯安裝)
5. [設定 BlueZ 組態](#5-設定-bluez-組態)
6. [重啟服務並測試](#6-重啟服務並測試)
7. [建立測試用的 GATT Server](#7-建立測試用的-gatt-server)
8. [驗證修改是否成功](#8-驗證修改是否成功)
9. [還原方法](#9-還原方法)

---

## 實作進度

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 1. 修改項目總覽 | ✅ 完成 | 新增「停用內建 DIS」項目 |
| 2. 準備工作環境 | ✅ 完成 | |
| 3. 修改原始碼 | 🔧 需重新編譯 | 新增 3.6 節修改 `gatt-database.c` |
| 4. 編譯安裝 | 🔧 需重新執行 | 修改程式碼後需重新編譯 |
| 5. 設定 BlueZ 組態 | ✅ 完成 | 可移除 `--noplugin` 設定 |
| 6. 重啟服務並測試 | 🔧 待執行 | 重新編譯後需重啟 |
| 7. 建立測試用的 GATT Server | ✅ 完成 | 7 Services 完整模擬 |
| 8. 驗證修改是否成功 | 🔧 待執行 | 需確認只有一個 DIS |
| 9. 還原方法 | 📋 備用 | |

### 待處理項目

| 項目 | 狀態 | 說明 |
|------|------|------|
| 移除重複 Device Information | ✅ 已解決 | 需修改 `src/gatt-database.c` 註解掉 `populate_devinfo_service()` |
| 移除 MIDI BLE Service | ✅ 已確認 | MIDI 未編譯進目前的 bluetoothd；若仍看到此服務需另外排查 |

**問題根因分析：**

1. **Device Information Service (0x180A)**
   - `--noplugin=deviceinfo` **無效**的原因：`deviceinfo` plugin 是用於**讀取遠端裝置**的 DIS，不是建立本地服務
   - 本地 DIS 服務是由 `src/gatt-database.c:populate_devinfo_service()` 建立的
   - **解決方案**：修改原始碼，註解掉 `populate_devinfo_service(database);` 呼叫

2. **MIDI Service (03b80e5a-...)**
   - 確認 `src/builtin.h` 中**沒有** midi 相關定義
   - MIDI 功能是編譯選項 (`--enable-midi`)，預設關閉
   - 若仍看到 MIDI 服務，可能來自系統原本的 bluetoothd 或其他程式

---

## 1. 修改項目總覽

| 項目 | 原因 | 優先級 |
|------|------|--------|
| 關閉 SMP Security Request | 印表機不需加密 | 必要 |
| 調整 GATT 權限預設值 | 避免自動要求加密 | 必要 |
| 設定 IO Capability 為 NoInputNoOutput | 模擬簡單裝置 | 建議 |
| 停用 Secure Connections | 某些舊手機相容性 | 視情況 |
| **停用內建 Device Information Service** | **避免與 Python 腳本重複** | **必要** |
| **停用安全等級提升** | **防止 kernel 發送 SMP Security Request** | **必要** |
| **停用 bondable 自動啟用** | **防止 bluetoothd 覆蓋 bondable off** | **建議** |

---

## 2. 準備工作環境

### 2.1 安裝編譯依賴

```bash
sudo apt update
sudo apt install -y build-essential libglib2.0-dev libdbus-1-dev \
    libudev-dev libical-dev libreadline-dev autoconf automake libtool \
    python3-docutils
```

### 2.2 下載原始碼

下載與目前系統版本相同的 BlueZ 原始碼（本例為 5.82）：

```bash
cd ~
wget http://www.kernel.org/pub/linux/bluetooth/bluez-5.82.tar.xz
tar xvf bluez-5.82.tar.xz
cd bluez-5.82
```

> **注意**：請根據你的 `bluetoothd --version` 輸出選擇對應版本。

---

## 3. 修改原始碼

### 3.1 關閉 SMP Security Request

編輯 `src/shared/att.c`：

```bash
nano src/shared/att.c
```

找到 `bt_att_set_security` 函式（約第 1992 行），修改為：

```c
bool bt_att_set_security(struct bt_att *att, int level)
{
    /* 強制跳過所有安全等級設定 */
    return true;
}
```

### 3.2 修改 GATT 權限檢查

編輯 `src/shared/gatt-server.c`：

```bash
nano src/shared/gatt-server.c
```

找到 `check_permissions` 函式（約第 410 行），修改為：

```c
static uint8_t check_permissions(struct bt_gatt_server *server,
                                struct gatt_db_attribute *attr,
                                uint32_t perm_mask)
{
    /* 跳過所有權限檢查，允許無加密存取 */
    return 0;
}
```

### 3.3 設定 IO Capability

編輯 `src/adapter.c`：

```bash
nano src/adapter.c
```

搜尋 `set_io_capability` 函式（約第 9083 行），確保設為：

```c
cp.capability = 0x03;  /* IO_CAPABILITY_NOINPUTNOOUTPUT - 強制無輸入輸出能力 */
```

IO Capability 常數定義：

```c
#define IO_CAPABILITY_DISPLAYONLY      0x00
#define IO_CAPABILITY_DISPLAYYESNO     0x01
#define IO_CAPABILITY_KEYBOARDONLY     0x02
#define IO_CAPABILITY_NOINPUTNOOUTPUT  0x03
#define IO_CAPABILITY_KEYBOARDDISPLAY  0x04
```

### 3.4 停用強制 Secure Connections（選用）

編輯 `src/adapter.c`：

```bash
nano src/adapter.c
```

搜尋 `MGMT_SETTING_SECURE_CONN`（約第 10290 行），將其註解掉：

```c
/* 停用強制 Secure Connections */
/* if (missing_settings & MGMT_SETTING_SECURE_CONN)
    set_mode(adapter, MGMT_OP_SET_SECURE_CONN,
                btd_opts.secure_conn); */
```

### 3.5 修改 SMP 配對行為

編輯 `src/shared/att.c`，找到 `bt_att_new` 函式（約第 1261 行），在 `bt_att_attach_chan(att, chan);` 之前加入：

```c
chan->sec_level = BT_ATT_SECURITY_LOW;  /* 強制使用最低安全等級 */
```

> **注意**：原指引寫 `att->sec_level`，但實際上 `sec_level` 是 `struct bt_att_chan` 的成員，應使用 `chan->sec_level`。

### 3.6 停用內建 Device Information Service

BlueZ 會自動建立一個只含 PnP ID 的 Device Information Service (0x180A)，會與 Python 腳本建立的完整 DIS 重複。

編輯 `src/gatt-database.c`：

```bash
nano src/gatt-database.c
```

找到約第 1516 行的 `populate_devinfo_service(database);` 呼叫，將其註解掉：

**修改前（約第 1514-1516 行）：**

```c
	populate_gap_service(database);
	populate_gatt_service(database);
	populate_devinfo_service(database);
```

**修改後：**

```c
	populate_gap_service(database);
	populate_gatt_service(database);
	/* 停用內建 Device Information Service，改由 Python 腳本提供完整 DIS */
	/* populate_devinfo_service(database); */
```

> **原理說明**：
> - `--noplugin=deviceinfo` 無法停用此服務，因為 `deviceinfo` plugin 是用於讀取遠端裝置的 DIS
> - 本地 GATT 服務是由 `gatt-database.c` 直接建立的，與 plugin 系統無關
> - 註解掉此行後，BlueZ 不會自動註冊 DIS，由 Python 腳本負責提供完整的 Device Information

### 3.7 停用安全等級提升（防止 SMP Security Request）

編輯 `src/device.c`，找到 `device_attach_att()` 函式中的安全等級提升邏輯（約第 5943 行），用 `#if 0` 停用：

**修改前：**

```c
	if (sec_level == BT_IO_SEC_LOW && dev->le_state.paired) {
		DBG("Elevating security level since LTK is available");

		sec_level = BT_IO_SEC_MEDIUM;
		bt_io_set(io, &gerr, BT_IO_OPT_SEC_LEVEL, sec_level,
							BT_IO_OPT_INVALID);
		if (gerr) {
			error("bt_io_set: %s", gerr->message);
			g_error_free(gerr);
			return false;
		}
	}
```

**修改後：**

```c
	/* 跳過安全等級提升，避免觸發 SMP Security Request。
	 * 原本會對已配對裝置提升至 BT_IO_SEC_MEDIUM，導致 kernel
	 * 發送 SMP Security Request (0x0b)，使 POS App 配對失敗。
	 */
#if 0
	if (sec_level == BT_IO_SEC_LOW && dev->le_state.paired) {
		...
	}
#endif
```

> **原理說明**：此路徑透過 `bt_io_set()` → `setsockopt(BT_SECURITY)` 直接操作 L2CAP socket，繞過了 3.1 節修改的 `bt_att_set_security()`。停用後 kernel 不再收到安全等級提升請求，不會發送 SMP Security Request (0x0b)。

### 3.8 停用 bondable 自動啟用

編輯 `src/adapter.c`，找到 `adapter_set_io_capability()` 函式中重新啟用 bondable 的邏輯（約第 9077 行），用 `#if 0` 停用：

**修改前：**

```c
		if (!(adapter->current_settings & MGMT_SETTING_BONDABLE))
			set_mode(adapter, MGMT_OP_SET_BONDABLE, 0x01);
```

**修改後：**

```c
		/* 不再於 agent 註冊時重新啟用 bondable，
		 * 避免覆蓋 btmgmt bondable off 的設定。
		 */
#if 0
		if (!(adapter->current_settings & MGMT_SETTING_BONDABLE))
			set_mode(adapter, MGMT_OP_SET_BONDABLE, 0x01);
#endif
```

> **原理說明**：當 D-Bus agent 註冊時會呼叫此函式，若 `btd_opts.pairable` 為 false（預設值），會自動重新啟用 bondable，覆蓋 `btmgmt bondable off` 的設定。

---

## 4. 編譯安裝

### 4.1 設定編譯選項

```bash
./configure --prefix=/usr --mandir=/usr/share/man \
    --sysconfdir=/etc --localstatedir=/var \
    --enable-experimental --enable-deprecated \
    --with-udevdir=/lib/udev \
    --with-systemdsystemunitdir=/lib/systemd/system \
    --with-systemduserunitdir=/usr/lib/systemd/user
```

> **注意**：原指引缺少 `--with-udevdir` 和 `--with-systemd*` 參數，在 Raspberry Pi OS 上必須加入這些參數才能正確編譯。

### 4.2 編譯

```bash
make -j4
```

> `-j4` 利用 Raspberry Pi 的四核心加速編譯，過程約需 10-20 分鐘。

### 4.3 備份原始檔案

```bash
sudo cp /usr/libexec/bluetooth/bluetoothd /usr/libexec/bluetooth/bluetoothd.backup
```

### 4.4 安裝

```bash
sudo make install
```

---

## 5. 設定 BlueZ 組態

編輯 `/etc/bluetooth/main.conf`：

```bash
sudo nano /etc/bluetooth/main.conf
```

加入或修改以下內容：

```ini
[General]
Name = BT-B36
Class = 0x000540
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = off
JustWorksRepairing = always

[Policy]
AutoEnable = true

[GATT]
ReconnectIntervals=1,2,4
```

> **注意**：BlueZ 5.82 的 main.conf 不支援 `DisablePlugins` 和 `Pairable` 設定鍵。
> 停用 plugin 需透過 systemd service 的 `--noplugin` 參數（見 5.2 節）。
> Pairable 由 Python 腳本透過 D-Bus adapter property 設定。

### 5.2 停用多餘的 BlueZ Plugin

真實 BT-B36 印表機沒有以下服務，但 BlueZ 會自動註冊：

| Plugin | 產生的多餘 Service | 說明 |
|--------|-------------------|------|
| `deviceinfo` | Device Information (0x180A) 含 PnP ID | 與腳本的完整 Device Information 重複 |
| `midi` | MIDI BLE Service (03b80e5a-...) | 印表機不需要 MIDI 功能 |

透過建立 systemd override 來傳入 `--noplugin` 參數：

```bash
sudo mkdir -p /etc/systemd/system/bluetooth.service.d
sudo tee /etc/systemd/system/bluetooth.service.d/override.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=deviceinfo,midi
EOF
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

> **說明**：第一行 `ExecStart=`（空值）是必要的，用來清除原本的 ExecStart，
> 否則 systemd 會同時執行兩個 ExecStart。

---

## 6. 重啟服務並測試

### 6.1 重新載入服務

```bash
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

### 6.2 確認版本

```bash
bluetoothd --version
```

### 6.3 監控 log 檢查錯誤

```bash
sudo journalctl -u bluetooth -f
```

---

## 7. 建立測試用的 GATT Server

### 7.1 安裝 Python 依賴

```bash
sudo apt install -y python3-dbus python3-gi
```

### 7.2 建立測試腳本

建立檔案 `~/test_gatt.py`：

```python
#!/usr/bin/env python3
"""
BT-B36 熱感印表機 BLE 模擬器
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ_SERVICE = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
LE_AD_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_AD_IFACE = 'org.bluez.LEAdvertisement1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'


class Application(dbus.service.Object):
    """GATT Application with ObjectManager interface"""

    def __init__(self, bus):
        self.path = '/org/bluez/example'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.characteristics:
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Advertisement(dbus.service.Object):
    """BLE 廣播物件"""
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = 'BT-B36'
        self.service_uuids = ['0000ff00-0000-1000-8000-00805f9b34fb']
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = {
            LE_AD_IFACE: {
                'Type': self.ad_type,
                'LocalName': dbus.String(self.local_name),
                'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
            }
        }
        return properties

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == LE_AD_IFACE:
            return self.get_properties()[LE_AD_IFACE]
        return {}

    @dbus.service.method(LE_AD_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Advertisement released')


class PrinterService(dbus.service.Object):
    """印表機 GATT Service"""

    def __init__(self, bus, index):
        self.path = '/org/bluez/example/service' + str(index)
        self.bus = bus
        self.uuid = '0000ff00-0000-1000-8000-00805f9b34fb'
        self.primary = True
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

        # 加入 Write Characteristic (ff02)
        self.characteristics.append(
            WriteCharacteristic(bus, 0, self, '0000ff02-0000-1000-8000-00805f9b34fb')
        )
        # 加入 Notify Characteristic (ff01)
        self.characteristics.append(
            NotifyCharacteristic(bus, 1, self, '0000ff01-0000-1000-8000-00805f9b34fb')
        )

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature='o'
                )
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == GATT_SERVICE_IFACE:
            return self.get_properties()[GATT_SERVICE_IFACE]
        return {}


class WriteCharacteristic(dbus.service.Object):
    """可寫入的 Characteristic，用於接收列印指令"""

    def __init__(self, bus, index, service, uuid):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = ['write-without-response', 'write']
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': dbus.Array(self.flags, signature='s'),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == GATT_CHRC_IFACE:
            return self.get_properties()[GATT_CHRC_IFACE]
        return {}

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        print(f'收到資料 [{self.uuid}]: {bytes(value).hex()}')
        self.value = value


class NotifyCharacteristic(dbus.service.Object):
    """Notify Characteristic"""

    def __init__(self, bus, index, service, uuid):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = ['notify']
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': dbus.Array(self.flags, signature='s'),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == GATT_CHRC_IFACE:
            return self.get_properties()[GATT_CHRC_IFACE]
        return {}

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print(f'Notify 已啟用 [{self.uuid}]')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print(f'Notify 已停用 [{self.uuid}]')


def main():
    """主程式"""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter_path = '/org/bluez/hci0'

    # 確保 adapter 已開啟並可被發現
    adapter = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        DBUS_PROP_IFACE
    )
    adapter.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(True))
    adapter.Set(ADAPTER_IFACE, 'Discoverable', dbus.Boolean(True))

    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        LE_AD_MANAGER_IFACE
    )
    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        GATT_MANAGER_IFACE
    )

    # 建立 Application 和 Service
    app = Application(bus)
    service = PrinterService(bus, 0)
    app.add_service(service)

    advertisement = Advertisement(bus, 0)

    # 註冊 GATT Application
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=lambda: print('GATT 服務已註冊'),
        error_handler=lambda e: print(f'GATT 註冊失敗: {e}')
    )

    # 註冊廣播
    ad_manager.RegisterAdvertisement(
        advertisement.path, {},
        reply_handler=lambda: print('廣播已註冊'),
        error_handler=lambda e: print(f'廣播註冊失敗: {e}')
    )

    print('BT-B36 模擬器啟動中...')
    print('按 Ctrl+C 結束')

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print('\n模擬器已停止')


if __name__ == '__main__':
    main()
```

> **注意**：原指引的腳本缺少 `Application` 類別的 `GetManagedObjects` 方法，會導致 GATT 註冊失敗。此版本已修正。

### 7.3 執行測試

```bash
python3 ~/test_gatt.py
```

預期輸出：
```
BT-B36 模擬器啟動中...
按 Ctrl+C 結束
GATT 服務已註冊
廣播已註冊
```

---

## 8. 驗證修改是否成功

使用另一台裝置（手機 + nRF Connect App）進行驗證。

### 8.1 模擬器 Services 對照表

腳本現在完整模擬真實 BT-B36 的 7 個 Services：

| # | Service UUID | 說明 | Characteristics |
|---|-------------|------|-----------------|
| 1 | `ff00` | 主要列印 Service | ff02 (Write), ff01 (Notify), ff03 (Notify) |
| 2 | `ff10` | 次要列印 Service | ff11 (Write+Notify), ff12 (Write+Notify) |
| 3 | `eee0` | Vendor Custom | eee1 (Write), eee1 (Notify) |
| 4 | `49535343-...` | Microchip UART | TX (Write), RX (Notify) |
| 5 | `18f0` | Unknown Service | 2af1 (Write), 2af0 (Notify) |
| 6 | `e7810a71-...` | Unknown Service | bef8d6c9 (R/W/Notify) |
| 7 | `180a` | Device Information | Manufacturer, Model, Serial, FW, HW, SW |

### 8.2 nRF Connect 操作說明

#### 連線

1. 開啟 nRF Connect App，切到 **Scanner** 頁面
2. 找到 **BT-B36**，點擊 **CONNECT**
3. 連線成功後會自動進入 Services 列表畫面

#### 訂閱 Notify（ff01 狀態回傳）

1. 展開 **Unknown Service (0000ff00-...)**
2. 找到 UUID `0000ff01-...` 的 Characteristic（標示 Notify）
3. 點擊該 Characteristic 右側的 **三個向下箭頭圖示**（Enable Notification）
4. 圖示變亮表示已訂閱成功
5. Pi 終端會顯示 `NOTIFY ON [0000ff01-...]`

#### 寫入資料到 ff02（模擬列印）

1. 同一個 Service 下，找到 UUID `0000ff02-...` 的 Characteristic（標示 Write）
2. 點擊該 Characteristic 右側的 **向上箭頭圖示**（Write Value）
3. 在彈出的對話框中：
   - 格式選 **HEX** 或 **UTF-8**
   - HEX 範例：`48656C6C6F` = "Hello"
   - UTF-8 範例：直接輸入 `Hello`
   - ESC 指令範例：`1B40` = ESC @ (印表機初始化)
4. 點擊 **SEND**

#### 預期結果

寫入後，Pi 終端會顯示：
```
  PRINT [0000ff02-...]: 48656c6c6f (5 bytes)
         Text: Hello
  -> NOTIFY [0000ff01-...]: 00
```

同時 nRF Connect 的 ff01 Characteristic 會收到通知值 `0x00`（印表機就緒）。

#### 讀取 Device Information

1. 展開 **Device Information (0x180A)**
2. 每個 Characteristic 右側有**向下箭頭**（Read Value），點擊可讀取
3. 應該看到：Manufacturer = "Printer", Model = "BT-B36" 等

### 8.3 驗證檢查清單

- [x] 裝置名稱顯示為 "BT-B36"
- [x] 可以成功連線
- [x] 可以發現全部 7 個 Services
- [x] 可以訂閱 ff01 Notify
- [x] 寫入 ff02 後 Pi 終端顯示收到的資料
- [x] 寫入 ff02 後 ff01 收到 ACK 通知（0x00）
- [x] Device Information 可讀取（Manufacturer, Model 等）
- [x] 終端機顯示所有操作的 log
- [ ] 只有一個 Device Information Service（無 BlueZ 內建重複）→ **套用 3.6 節修改後重新編譯即可解決**
- [x] 無多餘的 MIDI BLE Service → **確認 MIDI 未編譯進 bluetoothd**

---

## 9. 還原方法

如果需要還原至原始 BlueZ：

```bash
# 還原備份的 bluetoothd
sudo cp /usr/libexec/bluetooth/bluetoothd.backup /usr/libexec/bluetooth/bluetoothd

# 重啟服務
sudo systemctl restart bluetooth

# 確認版本
bluetoothd --version
```

或者重新安裝系統套件：

```bash
sudo apt install --reinstall bluez
```

---

## 附錄

### A. 常見問題排解

**Q: configure 時出現 udev directory is required 錯誤**

```bash
# 加入 --with-udevdir 參數
./configure ... --with-udevdir=/lib/udev
```

**Q: configure 時出現 systemd system unit directory is required 錯誤**

```bash
# 加入 systemd 相關參數
./configure ... \
    --with-systemdsystemunitdir=/lib/systemd/system \
    --with-systemduserunitdir=/usr/lib/systemd/user
```

**Q: 編譯時出現 'struct bt_att' has no member named 'sec_level' 錯誤**

這是因為 `sec_level` 是 `struct bt_att_chan` 的成員，不是 `struct bt_att`。應使用：
```c
chan->sec_level = BT_ATT_SECURITY_LOW;
```

**Q: 編譯時出現缺少標頭檔錯誤**

```bash
# 安裝額外的開發套件
sudo apt install -y libdbus-1-dev libudev-dev
```

**Q: 服務啟動失敗**

```bash
# 檢查詳細錯誤訊息
sudo journalctl -u bluetooth -n 50

# 手動啟動以查看錯誤
sudo /usr/libexec/bluetooth/bluetoothd -n -d
```

**Q: GATT 註冊失敗: No object received**

這是因為缺少 `ObjectManager` 介面。確保 `Application` 類別有實作 `GetManagedObjects` 方法。

**Q: 出現多餘的 Device Information Service**

BlueZ 會自動建立一個只含 PnP ID 的 Device Information Service (0x180A)。

> **重要**：`--noplugin=deviceinfo` **無法**解決此問題！
>
> **原因**：
> - `deviceinfo` plugin 是用於**讀取遠端裝置**的 DIS，不是建立本地服務
> - 本地 DIS 是由 `src/gatt-database.c:populate_devinfo_service()` 直接建立的

**正確解決方法**：修改 `src/gatt-database.c`，註解掉 `populate_devinfo_service(database);`（參見 3.6 節），然後重新編譯。

**Q: 出現多餘的 MIDI BLE Service**

MIDI 功能是編譯選項（`--enable-midi`），預設為關閉。確認方式：

```bash
# 檢查 MIDI 是否編譯進 bluetoothd
strings /usr/libexec/bluetooth/bluetoothd | grep -i midi
# 若無輸出表示 MIDI 未編譯
```

若仍看到 MIDI 服務，可能來自：
1. 系統原本安裝的 bluetoothd（非修改版）
2. 其他程式提供的 GATT 服務

確保使用的是修改後編譯的 bluetoothd：
```bash
which bluetoothd
bluetoothd --version
```

**Q: 廣播註冊失敗**

```bash
# 確認藍牙已啟用
sudo hciconfig hci0 up

# 確認 LE 功能已啟用
sudo btmgmt le on
```

### B. 相關資源

- [BlueZ 官方原始碼](http://www.kernel.org/pub/linux/bluetooth/)
- [BlueZ Git Repository](https://git.kernel.org/pub/scm/bluetooth/bluez.git)
- [nRF Connect App](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile)

---

## 版本資訊

- 文件版本：1.4
- 適用 BlueZ 版本：5.82
- 測試環境：Raspberry Pi OS (Kernel 6.12.47+rpt-rpi-v8)
- 最後更新：2026-02-2
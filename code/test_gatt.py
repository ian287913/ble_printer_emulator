#!/usr/bin/env python3
"""
BT-B36 熱感印表機 BLE 完整模擬器

完整模擬真實 BT-B36 的所有 BLE Services 和 Characteristics（參考 printer_info.json）。
收到列印資料時會在終端顯示，並透過 Notify 回傳印表機狀態。
"""

import subprocess
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# === D-Bus 介面常數 ===
BLUEZ_SERVICE = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
LE_AD_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_AD_IFACE = 'org.bluez.LEAdvertisement1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
AGENT_IFACE = 'org.bluez.Agent1'
AGENT_MANAGER_IFACE = 'org.bluez.AgentManager1'
AGENT_PATH = '/org/bluez/example/agent'


# === Agent ===

class Agent(dbus.service.Object):
    """NoInputNoOutput Agent — 自動接受所有配對請求"""

    def __init__(self, bus):
        dbus.service.Object.__init__(self, bus, AGENT_PATH)

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Agent released')

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        print(f'AuthorizeService: {device} {uuid}')

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        print(f'RequestPinCode: {device}')
        return '0000'

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        print(f'RequestPasskey: {device}')
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        print(f'DisplayPasskey: {device} {passkey}')

    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        print(f'RequestConfirmation: {device} {passkey} -- auto confirm')

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        print(f'RequestAuthorization: {device} -- auto authorize')

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Cancel(self):
        print('Agent Cancel')


# === GATT Application ===

class Application(dbus.service.Object):

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


# === Advertisement ===

class Advertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = 'BT-B36'
        self.service_uuids = ['0000ff00-0000-1000-8000-00805f9b34fb']
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            LE_AD_IFACE: {
                'Type': self.ad_type,
                'LocalName': dbus.String(self.local_name),
                'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == LE_AD_IFACE:
            return self.get_properties()[LE_AD_IFACE]
        return {}

    @dbus.service.method(LE_AD_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Advertisement released')


# === Generic Service ===

class Service(dbus.service.Object):

    def __init__(self, bus, index, uuid, primary=True):
        self.path = '/org/bluez/example/service' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, chrc):
        self.characteristics.append(chrc)

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

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == GATT_SERVICE_IFACE:
            return self.get_properties()[GATT_SERVICE_IFACE]
        return {}


# === Generic Characteristic ===

class Characteristic(dbus.service.Object):

    def __init__(self, bus, index, service, uuid, flags, value=None):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = list(value) if value else []
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': dbus.Array(self.flags, signature='s'),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == GATT_CHRC_IFACE:
            return self.get_properties()[GATT_CHRC_IFACE]
        return {}

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print(f'  READ  [{self.uuid}]: {bytes(self.value).hex() if self.value else "(empty)"}')
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        data = bytes(value)
        print(f'  WRITE [{self.uuid}]: {data.hex()} ({len(data)} bytes)')
        self.value = list(value)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print(f'  NOTIFY ON  [{self.uuid}]')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print(f'  NOTIFY OFF [{self.uuid}]')

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def send_notification(self, data):
        """發送 BLE Notification 給已訂閱的 client"""
        if not self.notifying:
            return False
        self.value = list(data)
        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {'Value': dbus.Array(data, signature='y')},
            []
        )
        print(f'  -> NOTIFY [{self.uuid}]: {bytes(data).hex()}')
        return True


# === 印表機 Write Characteristic（ff02 專用）===

class PrintWriteCharacteristic(Characteristic):
    """收到列印資料後解析內容，並透過 ff01 回傳 ACK"""

    def __init__(self, bus, index, service, uuid, flags):
        super().__init__(bus, index, service, uuid, flags)
        self.notify_chrc = None

    def set_notify_chrc(self, chrc):
        self.notify_chrc = chrc

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        data = bytes(value)
        print(f'  PRINT [{self.uuid}]: {data.hex()} ({len(data)} bytes)')

        # 嘗試解析內容
        if len(data) > 0 and data[0] == 0x1B:
            print(f'         ESC command: {data[1:].hex() if len(data) > 1 else ""}')
        elif len(data) > 0 and data[0] == 0x10:
            print(f'         DLE command: {data[1:].hex() if len(data) > 1 else ""}')
        else:
            try:
                text = data.decode('utf-8', errors='replace')
                print(f'         Text: {text}')
            except Exception:
                pass

        self.value = list(value)

        # 透過 ff01 回傳 ACK（模擬印表機就緒狀態 0x00）
        if self.notify_chrc:
            GLib.idle_add(self._send_ack)

    def _send_ack(self):
        if self.notify_chrc:
            self.notify_chrc.send_notification([0x00])
        return False


# === 建立所有 Services ===

def build_services(bus):
    """
    建立 printer_info.json 定義的 7 個 Services。
    回傳 (services_list, notify_chrc_ff01)。
    """
    services = []
    svc_idx = 0

    # -------------------------------------------------------
    # Service 1: ff00 — 主要列印 Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '0000ff00-0000-1000-8000-00805f9b34fb')
    svc_idx += 1

    # ff02: Write (列印資料入口) — handle 順序先於 ff01，與真實裝置一致
    chrc_ff02 = PrintWriteCharacteristic(
        bus, 0, svc,
        '0000ff02-0000-1000-8000-00805f9b34fb',
        ['write-without-response', 'write'],
    )
    svc.add_characteristic(chrc_ff02)

    # ff01: Notify (狀態回傳)
    chrc_ff01 = Characteristic(
        bus, 1, svc,
        '0000ff01-0000-1000-8000-00805f9b34fb',
        ['notify'],
    )
    svc.add_characteristic(chrc_ff01)

    # 將 ff01 連結到 ff02，讓 ff02 收到資料時可以回傳 ACK
    chrc_ff02.set_notify_chrc(chrc_ff01)

    # ff03: Notify (設定/控制通道)
    chrc_ff03 = Characteristic(
        bus, 2, svc,
        '0000ff03-0000-1000-8000-00805f9b34fb',
        ['notify'],
    )
    svc.add_characteristic(chrc_ff03)

    services.append(svc)

    # -------------------------------------------------------
    # Service 2: ff10 — 次要列印 Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '0000ff10-0000-1000-8000-00805f9b34fb')
    svc_idx += 1

    svc.add_characteristic(Characteristic(
        bus, 0, svc,
        '0000ff11-0000-1000-8000-00805f9b34fb',
        ['write-without-response', 'notify'],
    ))
    svc.add_characteristic(Characteristic(
        bus, 1, svc,
        '0000ff12-0000-1000-8000-00805f9b34fb',
        ['write-without-response', 'notify'],
    ))
    services.append(svc)

    # -------------------------------------------------------
    # Service 3: eee0 — Vendor Custom Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '0000eee0-0000-1000-8000-00805f9b34fb')
    svc_idx += 1

    # eee1 (Write) — 同 UUID 但不同用途，用不同 handle index 區分
    svc.add_characteristic(Characteristic(
        bus, 0, svc,
        '0000eee1-0000-1000-8000-00805f9b34fb',
        ['write-without-response', 'write'],
    ))
    # eee1 (Notify)
    svc.add_characteristic(Characteristic(
        bus, 1, svc,
        '0000eee1-0000-1000-8000-00805f9b34fb',
        ['notify'],
    ))
    services.append(svc)

    # -------------------------------------------------------
    # Service 4: Microchip UART Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '49535343-fe7d-4ae5-8fa9-9fafd205e455')
    svc_idx += 1

    # TX (Write)
    svc.add_characteristic(Characteristic(
        bus, 0, svc,
        '49535343-8841-43f4-a8d4-ecbe34729bb3',
        ['write-without-response', 'write'],
    ))
    # RX (Notify)
    svc.add_characteristic(Characteristic(
        bus, 1, svc,
        '49535343-1e4d-4bd9-ba61-23c647249616',
        ['notify'],
    ))
    services.append(svc)

    # -------------------------------------------------------
    # Service 5: 18f0 — Unknown Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '000018f0-0000-1000-8000-00805f9b34fb')
    svc_idx += 1

    svc.add_characteristic(Characteristic(
        bus, 0, svc,
        '00002af1-0000-1000-8000-00805f9b34fb',
        ['write-without-response', 'write'],
    ))
    svc.add_characteristic(Characteristic(
        bus, 1, svc,
        '00002af0-0000-1000-8000-00805f9b34fb',
        ['notify'],
    ))
    services.append(svc)

    # -------------------------------------------------------
    # Service 6: e7810a71 — Unknown Service
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, 'e7810a71-73ae-499d-8c15-faa9aef0c3f2')
    svc_idx += 1

    svc.add_characteristic(Characteristic(
        bus, 0, svc,
        'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f',
        ['read', 'write-without-response', 'write', 'notify'],
    ))
    services.append(svc)

    # -------------------------------------------------------
    # Service 7: 180a — Device Information
    # -------------------------------------------------------
    svc = Service(bus, svc_idx, '0000180a-0000-1000-8000-00805f9b34fb')
    svc_idx += 1

    dev_info = [
        ('00002a29-0000-1000-8000-00805f9b34fb', b'Printer'),       # Manufacturer Name
        ('00002a24-0000-1000-8000-00805f9b34fb', b'BT-B36'),        # Model Number
        ('00002a25-0000-1000-8000-00805f9b34fb', b'1023813F89B5'),  # Serial Number
        ('00002a26-0000-1000-8000-00805f9b34fb', b'0.1.3'),         # Firmware Revision
        ('00002a27-0000-1000-8000-00805f9b34fb', b'1.00'),          # Hardware Revision
        ('00002a28-0000-1000-8000-00805f9b34fb', b'1.00'),          # Software Revision
    ]
    for i, (uuid, val) in enumerate(dev_info):
        svc.add_characteristic(Characteristic(
            bus, i, svc, uuid, ['read'], value=val,
        ))
    services.append(svc)

    print(f'已建立 {len(services)} 個 Services')
    return services, chrc_ff01


# === Main ===

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter_path = '/org/bluez/hci0'

    # 設定 adapter
    adapter = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        DBUS_PROP_IFACE,
    )
    adapter.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(True))
    adapter.Set(ADAPTER_IFACE, 'Discoverable', dbus.Boolean(True))
    adapter.Set(ADAPTER_IFACE, 'Pairable', dbus.Boolean(False))

    # 關閉 bondable / SSP，減少不必要的配對請求
    subprocess.run(['sudo', 'btmgmt', 'bondable', 'off'], check=False)
    subprocess.run(['sudo', 'btmgmt', 'ssp', 'off'], check=False)
    print('已關閉 bondable 和 SSP')

    # 註冊 Agent（備用：若手機端主動發起配對，自動以 Just Works 處理）
    agent = Agent(bus)
    agent_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, '/org/bluez'),
        AGENT_MANAGER_IFACE,
    )
    agent_manager.RegisterAgent(AGENT_PATH, 'NoInputNoOutput')
    agent_manager.RequestDefaultAgent(AGENT_PATH)
    print('Agent 已註冊 (NoInputNoOutput)')

    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        LE_AD_MANAGER_IFACE,
    )
    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        GATT_MANAGER_IFACE,
    )

    # 建立所有 Services
    app = Application(bus)
    services, _notify_chrc = build_services(bus)
    for svc in services:
        app.add_service(svc)

    advertisement = Advertisement(bus, 0)

    # 註冊 GATT Application
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=lambda: print('GATT application 已註冊'),
        error_handler=lambda e: print(f'GATT 註冊失敗: {e}'),
    )

    # 註冊 BLE 廣播
    ad_manager.RegisterAdvertisement(
        advertisement.path, {},
        reply_handler=lambda: print('BLE 廣播已註冊'),
        error_handler=lambda e: print(f'廣播註冊失敗: {e}'),
    )

    print('')
    print('=== BT-B36 熱感印表機模擬器 ===')
    print('等待連線... (Ctrl+C 結束)')
    print('')

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print('\n模擬器已停止')


if __name__ == '__main__':
    main()

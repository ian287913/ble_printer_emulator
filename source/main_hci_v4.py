#!/usr/bin/env python3
"""
BLE Printer Emulator v4 - 完全無配對版本

關鍵改進：
1. 禁用 Pairable (避免觸發 SMP Security Request)
2. 移除 Agent 註冊 (不需要處理配對)
3. 簡化設定

使用方法:
    sudo python3 main_hci_v4.py
"""

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import sys
import datetime
import os
import subprocess

# =============================================================================
# 設定
# =============================================================================
DEVICE_NAME = "BT-B36"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "printer_data.log")

# BlueZ DBus
BLUEZ_SERVICE = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'
ADAPTER_IFACE = 'org.bluez.Adapter1'

# =============================================================================
# Service 和 Characteristic 定義
# =============================================================================
SERVICES = {
    "0000ff00-0000-1000-8000-00805f9b34fb": {
        "name": "Print Service",
        "chars": {
            "0000ff02-0000-1000-8000-00805f9b34fb": ["write-without-response", "write"],
            "0000ff01-0000-1000-8000-00805f9b34fb": ["notify"],
            "0000ff03-0000-1000-8000-00805f9b34fb": ["notify"],
        }
    },
    "0000ff10-0000-1000-8000-00805f9b34fb": {
        "name": "Print Service 2",
        "chars": {
            "0000ff11-0000-1000-8000-00805f9b34fb": ["write-without-response", "notify"],
            "0000ff12-0000-1000-8000-00805f9b34fb": ["write-without-response", "notify"],
        }
    },
    "0000eee0-0000-1000-8000-00805f9b34fb": {
        "name": "Custom Service",
        "chars": {
            "0000eee1-0000-1000-8000-00805f9b34fb": ["write-without-response", "write"],
            "0000eee2-0000-1000-8000-00805f9b34fb": ["notify"],
        }
    },
    "49535343-fe7d-4ae5-8fa9-9fafd205e455": {
        "name": "UART Service",
        "chars": {
            "49535343-8841-43f4-a8d4-ecbe34729bb3": ["write-without-response", "write"],
            "49535343-1e4d-4bd9-ba61-23c647249616": ["notify"],
        }
    },
    "000018f0-0000-1000-8000-00805f9b34fb": {
        "name": "Service 18F0",
        "chars": {
            "00002af1-0000-1000-8000-00805f9b34fb": ["write-without-response", "write"],
            "00002af0-0000-1000-8000-00805f9b34fb": ["notify"],
        }
    },
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2": {
        "name": "Service E781",
        "chars": {
            "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f": ["read", "write-without-response", "write", "notify"],
        }
    },
    "0000180a-0000-1000-8000-00805f9b34fb": {
        "name": "Device Information",
        "chars": {
            "00002a29-0000-1000-8000-00805f9b34fb": ["read"],
            "00002a24-0000-1000-8000-00805f9b34fb": ["read"],
            "00002a25-0000-1000-8000-00805f9b34fb": ["read"],
            "00002a26-0000-1000-8000-00805f9b34fb": ["read"],
            "00002a27-0000-1000-8000-00805f9b34fb": ["read"],
            "00002a28-0000-1000-8000-00805f9b34fb": ["read"],
        }
    },
}

DEVICE_INFO_VALUES = {
    "00002a29-0000-1000-8000-00805f9b34fb": b"Printer",
    "00002a24-0000-1000-8000-00805f9b34fb": b"BT-B36",
    "00002a25-0000-1000-8000-00805f9b34fb": b"1023813F89B5",
    "00002a26-0000-1000-8000-00805f9b34fb": b"0.1.3",
    "00002a27-0000-1000-8000-00805f9b34fb": b"1.00",
    "00002a28-0000-1000-8000-00805f9b34fb": b"1.00",
}

MAIN_NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

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
# 回應處理
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
# DBus Exceptions
# =============================================================================
class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'

class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotPermitted'

# =============================================================================
# GATT Classes
# =============================================================================
notify_chars = {}

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

        svc_index = 0
        for svc_uuid, svc_def in SERVICES.items():
            service = Service(bus, svc_index, svc_uuid, True)

            char_index = 0
            for char_uuid, char_flags in svc_def["chars"].items():
                char = Characteristic(bus, char_index, char_uuid, char_flags, service)
                service.add_characteristic(char)

                if "notify" in char_flags:
                    notify_chars[char_uuid] = char

                char_index += 1

            self.services.append(service)
            svc_index += 1

        log(f"Created {len(self.services)} services")

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.get_characteristics():
                response[chrc.get_path()] = chrc.get_properties()
                for desc in chrc.get_descriptors():
                    response[desc.get_path()] = desc.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        self.notifying = False

        if uuid in DEVICE_INFO_VALUES:
            self.value = [dbus.Byte(b) for b in DEVICE_INFO_VALUES[uuid]]
        else:
            self.value = []

        dbus.service.Object.__init__(self, bus, self.path)

        if "notify" in flags:
            self.add_descriptor(CCCDescriptor(bus, 0, self))

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Descriptors': dbus.Array(
                    [d.get_path() for d in self.descriptors],
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        log(f'Read: {self.uuid[-8:]}')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        data = bytes(value)
        log_data(data, self.uuid[-8:])
        self.value = value

        response = process_command(data)
        if response:
            send_notification(response)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        log(f'StartNotify: {self.uuid[-8:]}')
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        log(f'StopNotify: {self.uuid[-8:]}')
        self.notifying = False

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def notify(self, value):
        if not self.notifying:
            return
        self.value = [dbus.Byte(b) for b in value]
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': self.value}, [])


class CCCDescriptor(dbus.service.Object):
    CCC_UUID = '2902'

    def __init__(self, bus, index, characteristic):
        self.path = characteristic.path + '/desc' + str(index)
        self.bus = bus
        self.uuid = self.CCC_UUID
        self.flags = ['read', 'write']
        self.chrc = characteristic
        self.value = [dbus.Byte(0), dbus.Byte(0)]
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_DESC_IFACE: {
                'Characteristic': self.chrc.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_DESC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_DESC_IFACE]

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return self.value

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value
        if len(value) >= 1 and value[0] & 0x01:
            self.chrc.StartNotify()
        else:
            self.chrc.StopNotify()


def send_notification(data: bytes):
    if MAIN_NOTIFY_UUID in notify_chars:
        char = notify_chars[MAIN_NOTIFY_UUID]
        if char.notifying:
            char.notify(data)
            log(f'Notification sent: {data.hex(" ")}')

# =============================================================================
# Helper Functions
# =============================================================================
def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o
    return None

def setup_btmgmt():
    """使用 btmgmt 設定關鍵參數"""
    commands = [
        ['btmgmt', 'bondable', 'off'],
        ['btmgmt', 'ssp', 'off'],
        ['btmgmt', 'sc', 'off'],
        ['btmgmt', 'io-cap', '3'],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                log(f"  {' '.join(cmd)}: OK")
            else:
                log(f"  {' '.join(cmd)}: {result.stderr.strip()}")
        except Exception as e:
            log(f"  {' '.join(cmd)}: Error - {e}")

# =============================================================================
# Main
# =============================================================================
def main():
    print(f"\n{'='*60}")
    print(f"BLE Printer Emulator v4 - {DEVICE_NAME}")
    print(f"No Pairing / No Security Request")
    print(f"{'='*60}\n")

    # 初始化日誌
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Session: {datetime.datetime.now().isoformat()}\n")
            f.write(f"{'='*60}\n")
    except:
        pass

    # 使用 btmgmt 設定
    log("Configuring bluetooth with btmgmt...")
    setup_btmgmt()

    # 初始化 DBus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter = find_adapter(bus)
    if not adapter:
        log('ERROR: BLE adapter not found')
        return 1

    log(f'Adapter: {adapter}')

    # 設定 Adapter - 關鍵：禁用 Pairable!
    try:
        adapter_obj = bus.get_object(BLUEZ_SERVICE, adapter)
        adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

        adapter_props.Set(ADAPTER_IFACE, "Alias", DEVICE_NAME)
        adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
        adapter_props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True))
        adapter_props.Set(ADAPTER_IFACE, "DiscoverableTimeout", dbus.UInt32(0))

        # 關鍵：禁用 Pairable 以避免 SMP Security Request
        adapter_props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(False))
        adapter_props.Set(ADAPTER_IFACE, "PairableTimeout", dbus.UInt32(0))

        log("Adapter configured (Pairable=False)")
    except Exception as e:
        log(f"Warning: Adapter config error: {e}")

    # 不註冊 Agent - 不需要處理配對請求
    log("Agent registration skipped (Pairable=False)")

    service_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter),
        GATT_MANAGER_IFACE)

    app = Application(bus)

    mainloop = GLib.MainLoop()

    def register_app_cb():
        log('GATT application registered')
        log('')
        log('='*60)
        log(f'READY! "{DEVICE_NAME}" is advertising')
        log('='*60)
        log('')
        log('Configuration:')
        log('  - Pairable: False')
        log('  - Bondable: Off')
        log('  - SSP: Off')
        log('  - Secure Connections: Off')
        log('')
        log('Services:')
        for svc_uuid, svc_def in SERVICES.items():
            log(f'  - {svc_def["name"]} ({svc_uuid[-8:-4]})')
        log('')
        log('Waiting for connections...')
        log('')

    def register_app_error_cb(error):
        log(f'Failed to register app: {error}')
        mainloop.quit()

    log('Registering GATT application...')
    service_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=register_app_cb,
        error_handler=register_app_error_cb)

    try:
        mainloop.run()
    except KeyboardInterrupt:
        log('\nShutting down...')

    return 0

if __name__ == '__main__':
    sys.exit(main())

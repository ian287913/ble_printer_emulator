#!/usr/bin/env python3
"""
auto_pair_agent.py - 獨立的自動配對 Agent

這個程式需要在執行 BLE 模擬器之前單獨執行
它會攔截所有配對請求並自動接受

使用方法：
    終端機 1: sudo python3 auto_pair_agent.py
    終端機 2: sudo python3 main_hci.py
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import sys

BUS_NAME = 'org.bluez'
AGENT_INTERFACE = 'org.bluez.Agent1'
AGENT_PATH = "/test/autoagent"

class AutoPairAgent(dbus.service.Object):
    """自動接受所有配對請求的 Agent"""
    
    exit_on_release = True
    
    def set_exit_on_release(self, exit_on_release):
        self.exit_on_release = exit_on_release

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        print("Agent: Release")
        if self.exit_on_release:
            mainloop.quit()

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"Agent: AuthorizeService ({device}, {uuid}) -> OK")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"Agent: RequestPinCode ({device}) -> '0000'")
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"Agent: RequestPasskey ({device}) -> 0")
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"Agent: DisplayPasskey ({device}, {passkey:06d} entered {entered})")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"Agent: DisplayPinCode ({device}, {pincode})")

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"Agent: RequestConfirmation ({device}, {passkey:06d}) -> CONFIRMED!")
        # 回傳空 = 確認
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"Agent: RequestAuthorization ({device}) -> AUTHORIZED!")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("Agent: Cancel")


def main():
    global mainloop
    
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    bus = dbus.SystemBus()
    
    # 建立 agent
    agent = AutoPairAgent(bus, AGENT_PATH)
    agent.set_exit_on_release(False)
    
    # 取得 AgentManager
    obj = bus.get_object(BUS_NAME, "/org/bluez")
    manager = dbus.Interface(obj, "org.bluez.AgentManager1")
    
    # 先嘗試取消註冊舊的
    try:
        manager.UnregisterAgent(AGENT_PATH)
        print("Unregistered old agent")
    except:
        pass
    
    # 註冊新的 agent
    manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    print("Agent registered with NoInputNoOutput capability")
    
    # 設為預設
    manager.RequestDefaultAgent(AGENT_PATH)
    print("Agent is now the default")
    
    print("")
    print("="*50)
    print("Auto-Pair Agent is running!")
    print("All pairing requests will be automatically accepted.")
    print("Press Ctrl+C to exit.")
    print("="*50)
    print("")
    
    mainloop = GLib.MainLoop()
    
    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        try:
            manager.UnregisterAgent(AGENT_PATH)
        except:
            pass

if __name__ == '__main__':
    main()

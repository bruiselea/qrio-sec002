"""Temporary BlueZ Just Works agent restricted to the selected owned device."""

from dbus_fast import BusType, DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method


class Agent(ServiceInterface):
    def __init__(self, device_path):
        super().__init__("org.bluez.Agent1")
        self.device_path = device_path

    def check(self, device):
        if device != self.device_path:
            raise DBusError("org.bluez.Error.Rejected", "This agent only serves its selected Q-SL1")

    @method()
    def Release(self):
        pass

    @method()
    def Cancel(self):
        pass

    @method()
    def RequestPinCode(self, device: 'o') -> 's':
        raise DBusError("org.bluez.Error.Rejected", "Unexpected PIN request")

    @method()
    def RequestPasskey(self, device: 'o') -> 'u':
        raise DBusError("org.bluez.Error.Rejected", "Unexpected passkey request")

    @method()
    def RequestConfirmation(self, device: 'o', passkey: 'u'):
        self.check(device)

    @method()
    def RequestAuthorization(self, device: 'o'):
        self.check(device)

    @method()
    def AuthorizeService(self, device: 'o', service_uuid: 's'):
        self.check(device)


class PairingAgent:
    async def start(self, device_path):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self.path = "/qrio/sl1/agent"
        self.bus.export(self.path, Agent(device_path))
        info = await self.bus.introspect("org.bluez", "/org/bluez")
        self.manager = self.bus.get_proxy_object("org.bluez", "/org/bluez", info).get_interface("org.bluez.AgentManager1")
        await self.manager.call_register_agent(self.path, "NoInputNoOutput")
        await self.manager.call_request_default_agent(self.path)

    async def close(self):
        try:
            await self.manager.call_unregister_agent(self.path)
        finally:
            self.bus.disconnect()

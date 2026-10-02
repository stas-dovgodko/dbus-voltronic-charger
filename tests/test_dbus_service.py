import os
import sys
import tempfile
import types
import unittest

from voltronic_charger.config import load_config
from voltronic_charger.dbus_service import ChargerDbusService
from voltronic_charger.parser import parse_qpigs_pi30
from tests.test_parser import DOCUMENTED_SHAPE


class FakeVeDbusService:
    def __init__(self, name, bus=None, register=None):
        self.name = name
        self.values = {}
        self.registered = False

    def add_path(self, path, value=None, **_arguments):
        self.values[path] = value

    def register(self):
        self.registered = True

    def __setitem__(self, path, value):
        self.values[path] = value


def config_text(publish):
    return """[serial]
port=/dev/serial/by-id/example
[protocol]
profile=pi30
publish_battery_charging_current={}
[device]
model=Voltronic King II 5000
custom_name=King II
device_instance=40
service_name=com.victronenergy.charger.voltronic_king2
[driver]
poll_interval=5
failure_threshold=3
""".format(str(publish).lower())


class DbusServiceTest(unittest.TestCase):
    def setUp(self):
        self.original_vedbus = sys.modules.get("vedbus")
        sys.modules["vedbus"] = types.SimpleNamespace(VeDbusService=FakeVeDbusService)

    def tearDown(self):
        if self.original_vedbus is None:
            sys.modules.pop("vedbus", None)
        else:
            sys.modules["vedbus"] = self.original_vedbus

    def _config(self, publish):
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        try:
            handle.write(config_text(publish))
            handle.close()
            return load_config(handle.name)
        finally:
            os.unlink(handle.name)

    def test_default_does_not_publish_unverified_current_or_stage(self):
        service = ChargerDbusService(self._config(False))
        service.publish(parse_qpigs_pi30(DOCUMENTED_SHAPE))
        values = service._service.values
        self.assertEqual(1, values["/Connected"])
        self.assertEqual(52.4, values["/Dc/0/Voltage"])
        self.assertIsNone(values["/Dc/0/Current"])
        self.assertIsNone(values["/Dc/0/Power"])
        self.assertIsNone(values["/State"])

if __name__ == "__main__":
    unittest.main()

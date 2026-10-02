import os
import tempfile
import unittest

from voltronic_charger.config import load_config


BASE = """[serial]
port = {port}
baudrate = 2400
timeout = 2
[protocol]
profile = {profile}
publish_battery_charging_current = {publish}
[device]
model = Voltronic King II 5000
custom_name = King II
device_instance = 40
service_name = com.victronenergy.charger.voltronic_king2
[driver]
poll_interval = 5
failure_threshold = 3
"""


class ConfigTest(unittest.TestCase):
    def _load(self, **values):
        content = BASE.format(
            port=values.get("port", "/dev/serial/by-id/example"),
            profile=values.get("profile", "unconfirmed"),
            publish=str(values.get("publish", False)).lower(),
        )
        if values.get("missing_instance"):
            content = content.replace("device_instance = 40", "device_instance =")
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        try:
            handle.write(content)
            handle.close()
            return load_config(handle.name)
        finally:
            os.unlink(handle.name)

    def test_safe_defaults_load_but_are_unconfirmed(self):
        config = self._load()
        self.assertEqual("unconfirmed", config.protocol.profile)
        self.assertFalse(config.protocol.publish_battery_charging_current)

    def test_configured_port_is_preserved_verbatim(self):
        config = self._load(port="/dev/ttyUSB1")
        self.assertEqual("/dev/ttyUSB1", config.serial.port)

    def test_port_is_required(self):
        with self.assertRaises(ValueError):
            self._load(port="")

    def test_device_instance_is_required(self):
        with self.assertRaises(ValueError):
            self._load(missing_instance=True)

    def test_current_publication_is_disabled_until_validated(self):
        with self.assertRaises(ValueError):
            self._load(profile="unconfirmed", publish=True)
        with self.assertRaises(ValueError):
            self._load(profile="pi30", publish=True)


if __name__ == "__main__":
    unittest.main()

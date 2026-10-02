import os
import tempfile
import unittest

from voltronic_charger.config import load_config


BASE = """[serial]
port = {port}
baudrate = 2400
timeout = 2
command_delay = {command_delay}
[protocol]
profile = {profile}
publish_battery_charging_current = {publish}
[power_estimation]
self_consumption_watts = {self_consumption_watts}
ac_to_dc_efficiency_percent = {efficiency_percent}
[device]
model = Voltronic King II 5000
custom_name = King II
device_instance = 40
service_name = com.victronenergy.charger.voltronic_king2
[driver]
poll_interval = 5
failure_threshold = 3
[control]
    allow_current_limit_writes = {allow_writes}
    parallel_unit = {parallel_unit}
    utility_current_format = {utility_current_format}
    allow_mode_writes = {allow_mode_writes}
    enabled_charger_source_priority = {enabled_priority}
"""


class ConfigTest(unittest.TestCase):
    def _load(self, **values):
        content = BASE.format(
            port=values.get("port", "/dev/serial/by-id/example"),
            command_delay=values.get("command_delay", 0.5),
            profile=values.get("profile", "pi30"),
            publish=str(values.get("publish", True)).lower(),
            self_consumption_watts=values.get("self_consumption_watts", 70),
            efficiency_percent=values.get("efficiency_percent", 95),
            allow_writes=str(values.get("allow_writes", False)).lower(),
            parallel_unit=values.get("parallel_unit", 0),
            utility_current_format=values.get("utility_current_format", "auto"),
            allow_mode_writes=str(values.get("allow_mode_writes", False)).lower(),
            enabled_priority=values.get("enabled_priority", ""),
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

    def test_confirmed_profile_and_current_publication_load(self):
        config = self._load()
        self.assertEqual("pi30", config.protocol.profile)
        self.assertTrue(config.protocol.publish_battery_charging_current)
        self.assertEqual(0.5, config.serial.command_delay)
        self.assertEqual(70.0, config.power_estimation.self_consumption_watts)
        self.assertEqual(
            95.0,
            config.power_estimation.ac_to_dc_efficiency_percent,
        )

    def test_current_publication_can_be_disabled(self):
        config = self._load(publish=False)
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

    def test_negative_command_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            self._load(command_delay=-0.1)

    def test_current_limit_writes_are_explicitly_opt_in(self):
        self.assertFalse(self._load().control.allow_current_limit_writes)
        self.assertTrue(
            self._load(allow_writes=True).control.allow_current_limit_writes
        )

    def test_parallel_unit_is_validated(self):
        with self.assertRaises(ValueError):
            self._load(parallel_unit=10)

    def test_utility_current_format_is_configurable_and_validated(self):
        self.assertEqual("auto", self._load().control.utility_current_format)
        self.assertEqual(
            "standard",
            self._load(utility_current_format="standard").control.utility_current_format,
        )
        self.assertEqual(
            "parallel",
            self._load(utility_current_format="parallel").control.utility_current_format,
        )
        with self.assertRaises(ValueError):
            self._load(utility_current_format="unknown")

    def test_mode_writes_are_explicitly_opt_in(self):
        self.assertFalse(self._load().control.allow_mode_writes)
        self.assertTrue(self._load(allow_mode_writes=True).control.allow_mode_writes)
        self.assertEqual(
            2,
            self._load(enabled_priority=2).control.enabled_charger_source_priority,
        )
        with self.assertRaises(ValueError):
            self._load(enabled_priority=3)

    def test_power_estimation_values_are_configurable_and_validated(self):
        config = self._load(self_consumption_watts=85, efficiency_percent=92.5)
        self.assertEqual(85.0, config.power_estimation.self_consumption_watts)
        self.assertEqual(
            92.5,
            config.power_estimation.ac_to_dc_efficiency_percent,
        )
        for self_consumption in (-1, "nan", "inf"):
            with self.subTest(self_consumption=self_consumption):
                with self.assertRaises(ValueError):
                    self._load(self_consumption_watts=self_consumption)
        for efficiency in (0, 101, "nan", "inf"):
            with self.subTest(efficiency=efficiency):
                with self.assertRaises(ValueError):
                    self._load(efficiency_percent=efficiency)

    def test_missing_power_estimation_section_uses_documented_defaults(self):
        content = BASE.format(
            port="/dev/ttyUSB1",
            command_delay=0.5,
            profile="pi30",
            publish="true",
            self_consumption_watts=70,
            efficiency_percent=95,
            allow_writes="false",
            parallel_unit=0,
            utility_current_format="auto",
            allow_mode_writes="false",
            enabled_priority="",
        )
        content = content.replace(
            "[power_estimation]\n"
            "self_consumption_watts = 70\n"
            "ac_to_dc_efficiency_percent = 95\n",
            "",
        )
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        try:
            handle.write(content)
            handle.close()
            config = load_config(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(70.0, config.power_estimation.self_consumption_watts)
        self.assertEqual(
            95.0,
            config.power_estimation.ac_to_dc_efficiency_percent,
        )

    def test_missing_control_section_defaults_to_read_only(self):
        content = BASE.format(
            port="/dev/ttyUSB1",
            command_delay=0.5,
            profile="pi30",
            publish="true",
            self_consumption_watts=70,
            efficiency_percent=95,
            allow_writes="false",
            parallel_unit=0,
            utility_current_format="auto",
            allow_mode_writes="false",
            enabled_priority="",
        ).split("[control]", 1)[0]
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        try:
            handle.write(content)
            handle.close()
            config = load_config(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertFalse(config.control.allow_current_limit_writes)
        self.assertEqual(0, config.control.parallel_unit)
        self.assertEqual("auto", config.control.utility_current_format)

    def test_missing_device_labels_use_generic_defaults(self):
        content = BASE.format(
            port="/dev/ttyUSB1",
            command_delay=0.5,
            profile="pi30",
            publish="true",
            self_consumption_watts=70,
            efficiency_percent=95,
            allow_writes="false",
            parallel_unit=0,
            utility_current_format="auto",
            allow_mode_writes="false",
            enabled_priority="",
        )
        content = content.replace("model = Voltronic King II 5000\n", "")
        content = content.replace("custom_name = King II\n", "")
        content = content.replace(
            "service_name = com.victronenergy.charger.voltronic_king2\n",
            "",
        )
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        try:
            handle.write(content)
            handle.close()
            config = load_config(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual("Voltronic PI30 Charger", config.device.model)
        self.assertEqual("Voltronic PI30 Charger", config.device.custom_name)
        self.assertEqual(
            "com.victronenergy.charger.voltronic_pi30",
            config.device.service_name,
        )


if __name__ == "__main__":
    unittest.main()

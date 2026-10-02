from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "install.sh",
    "activate.sh",
    "deactivate.sh",
    "uninstall.sh",
    "serial-port.sh",
    "service/run",
    "service/log/run",
)


class PackagingSafetyTest(unittest.TestCase):
    def test_packaging_scripts_exist_and_use_posix_shell(self):
        for relative in SCRIPTS:
            with self.subTest(relative=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertTrue(content.startswith("#!/bin/sh\n"))
                self.assertIn("set -eu", content)

    def test_packaging_has_no_recursive_delete_or_forced_symlink_replace(self):
        for relative in SCRIPTS:
            with self.subTest(relative=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("rm -rf", content)
                self.assertNotIn("ln -sfn", content)
                self.assertNotIn("serial-starter.d", content)

    def test_sample_matches_confirmed_full_driver(self):
        content = (ROOT / "config.ini.example").read_text(encoding="utf-8")
        self.assertIn("port = /dev/ttyUSB1", content)
        self.assertIn("profile = pi30", content)
        self.assertIn("publish_battery_charging_current = true", content)
        self.assertIn("self_consumption_watts = 70", content)
        self.assertIn("ac_to_dc_efficiency_percent = 95", content)
        self.assertIn("allow_current_limit_writes = false", content)
        self.assertIn("allow_mode_writes = false", content)
        self.assertRegex(content, r"(?m)^device_instance =\s*$")

    def test_serial_lifecycle_targets_only_the_configured_port(self):
        helper = (ROOT / "serial-port.sh").read_text(encoding="utf-8")
        service = (ROOT / "service/run").read_text(encoding="utf-8")
        deactivate = (ROOT / "deactivate.sh").read_text(encoding="utf-8")
        self.assertIn('load_config(sys.argv[1]).serial.port', helper)
        self.assertIn('stop-tty.sh', helper)
        self.assertIn('start-tty.sh', helper)
        self.assertNotIn("ttyUSB0", helper)
        self.assertNotIn("ttyUSB1", helper)
        self.assertIn('serial-port.sh" acquire', service)
        self.assertIn('serial-port.sh" release', deactivate)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "install.sh",
    "activate.sh",
    "deactivate.sh",
    "uninstall.sh",
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

    def test_sample_remains_fail_closed(self):
        content = (ROOT / "config.ini.example").read_text(encoding="utf-8")
        self.assertIn("port = /dev/ttyUSB1", content)
        self.assertIn("profile = unconfirmed", content)
        self.assertIn("publish_battery_charging_current = false", content)
        self.assertRegex(content, r"(?m)^device_instance =\s*$")


if __name__ == "__main__":
    unittest.main()


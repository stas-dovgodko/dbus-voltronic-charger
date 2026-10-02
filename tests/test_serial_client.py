import sys
import types
import unittest

from voltronic_charger.protocol import ProtocolError, crc_bytes
from voltronic_charger.serial_client import SerialQueryClient


class FakeSerial:
    def __init__(self, response):
        self.response = response
        self.writes = []
        self.closed = False
        self.reset_count = 0

    def reset_input_buffer(self):
        self.reset_count += 1

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass

    def read_until(self, _marker):
        return self.response

    def close(self):
        self.closed = True


class SerialClientTest(unittest.TestCase):
    def test_query_writes_only_encoded_allowlisted_command(self):
        payload = b"(PI30"
        fake = FakeSerial(payload + crc_bytes(payload) + b"\r")
        client = SerialQueryClient("fake", serial_instance=fake)
        self.assertEqual("(PI30", client.query("QPI"))
        self.assertEqual([b"QPI\xbe\xac\r"], fake.writes)
        self.assertEqual(1, fake.reset_count)

    def test_rejected_command_never_reaches_serial(self):
        fake = FakeSerial(b"")
        client = SerialQueryClient("fake", serial_instance=fake)
        with self.assertRaises(ProtocolError):
            client.query("POP00")
        self.assertEqual([], fake.writes)

    def test_configured_port_is_passed_unchanged_to_pyserial(self):
        payload = b"(PI30"
        response = payload + crc_bytes(payload) + b"\r"
        opened_with = {}

        def open_serial(**kwargs):
            opened_with.update(kwargs)
            return FakeSerial(response)

        original = sys.modules.get("serial")
        sys.modules["serial"] = types.SimpleNamespace(
            Serial=open_serial,
            EIGHTBITS=8,
            PARITY_NONE="N",
            STOPBITS_ONE=1,
        )
        try:
            client = SerialQueryClient("/dev/ttyUSB1", baudrate=2400, timeout=2)
            self.assertEqual("(PI30", client.query("QPI"))
            self.assertEqual("/dev/ttyUSB1", opened_with["port"])
            self.assertEqual(2400, opened_with["baudrate"])
        finally:
            client.close()
            if original is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = original


if __name__ == "__main__":
    unittest.main()

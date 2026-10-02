import sys
import types
import unittest
from unittest import mock

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
        if isinstance(self.response, list):
            return self.response.pop(0)
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

    def test_configurable_delay_paces_back_to_back_queries(self):
        payload = b"(PI30"
        response = payload + crc_bytes(payload) + b"\r"
        fake = FakeSerial(response)
        client = SerialQueryClient(
            "fake", command_delay=0.5, serial_instance=fake
        )
        with mock.patch(
            "voltronic_charger.serial_client.time.monotonic",
            side_effect=(10.0, 10.1),
        ), mock.patch("voltronic_charger.serial_client.time.sleep") as sleep:
            client.query("QPI")
            client.query("QPI")
        sleep.assert_called_once()
        self.assertAlmostEqual(0.4, sleep.call_args.args[0])

    def test_standard_utility_current_setting_requires_ack(self):
        payload = b"(ACK"
        fake = FakeSerial(payload + crc_bytes(payload) + b"\r")
        client = SerialQueryClient("fake", serial_instance=fake)
        client.set_charge_current_limit("utility", 2)
        command = b"MUCHGC002"
        self.assertEqual([command + crc_bytes(command) + b"\r"], fake.writes)

    def test_auto_utility_format_falls_back_and_caches_parallel_variant(self):
        ack = b"(ACK" + crc_bytes(b"(ACK") + b"\r"
        nak = b"(NAK" + crc_bytes(b"(NAK") + b"\r"
        fake = FakeSerial([nak, ack, ack])
        client = SerialQueryClient("fake", serial_instance=fake)

        client.set_charge_current_limit("utility", 20, 0, "auto")
        client.set_charge_current_limit("utility", 30, 0, "auto")

        commands = (b"MUCHGC020", b"MUCHGC0020", b"MUCHGC0030")
        self.assertEqual(
            [command + crc_bytes(command) + b"\r" for command in commands],
            fake.writes,
        )

    def test_current_setting_rejects_nak(self):
        payload = b"(NAK"
        fake = FakeSerial(payload + crc_bytes(payload) + b"\r")
        client = SerialQueryClient("fake", serial_instance=fake)
        with self.assertRaises(ProtocolError):
            client.set_charge_current_limit("total", 60)

    def test_charger_source_priority_setting_requires_ack(self):
        payload = b"(ACK"
        fake = FakeSerial(payload + crc_bytes(payload) + b"\r")
        client = SerialQueryClient("fake", serial_instance=fake)
        client.set_charger_source_priority(3)
        command = b"PCP03"
        self.assertEqual([command + crc_bytes(command) + b"\r"], fake.writes)


if __name__ == "__main__":
    unittest.main()

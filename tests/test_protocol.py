import unittest

from voltronic_charger.protocol import (
    ProtocolError,
    crc_bytes,
    decode_response,
    encode_charger_source_priority,
    encode_charge_current_setting,
    encode_query,
)


class ProtocolTest(unittest.TestCase):
    def test_known_query_vectors(self):
        self.assertEqual(b"QPIGS\xb7\xa9\r", encode_query("QPIGS"))
        self.assertEqual(b"QPI\xbe\xac\r", encode_query("QPI"))

    def test_round_trip_response_validation(self):
        payload = b"(PI30"
        frame = payload + crc_bytes(payload) + b"\r"
        self.assertEqual("(PI30", decode_response(frame))

    def test_rejects_non_inquiry_before_transport(self):
        for command in ("POP00", "PBT01", "MCHGC060", "PF", "qpigs", ""):
            with self.subTest(command=command):
                with self.assertRaises(ProtocolError):
                    encode_query(command)

    def test_rejects_bad_crc_and_incomplete_frame(self):
        with self.assertRaises(ProtocolError):
            decode_response(b"(PI30\x00\x00\r")
        with self.assertRaises(ProtocolError):
            decode_response(b"(PI30")

    def test_current_setting_frames_are_narrowly_constructed(self):
        for scope, current, expected_payload in (
            ("total", 60, b"MCHGC060"),
            ("total", 140, b"MNCHGC0140"),
            ("utility", 2, b"MUCHGC002"),
        ):
            with self.subTest(scope=scope, current=current):
                self.assertEqual(
                    expected_payload + crc_bytes(expected_payload) + b"\r",
                    encode_charge_current_setting(scope, current),
                )

    def test_parallel_utility_setting_includes_configured_unit(self):
        payload = b"MUCHGC3020"
        self.assertEqual(
            payload + crc_bytes(payload) + b"\r",
            encode_charge_current_setting(
                "utility",
                20,
                parallel_unit=3,
                utility_current_format="parallel",
            ),
        )

    def test_current_setting_rejects_unscoped_or_invalid_values(self):
        for scope, current in (
            ("other", 60),
            ("total", -1),
            ("total", 1000),
            ("utility", 2.5),
            ("utility", True),
        ):
            with self.subTest(scope=scope, current=current):
                with self.assertRaises(ProtocolError):
                    encode_charge_current_setting(scope, current)

        with self.assertRaises(ProtocolError):
            encode_charge_current_setting(
                "utility",
                20,
                utility_current_format="auto",
            )

    def test_charger_source_priority_frames_are_narrowly_constructed(self):
        command = b"PCP03"
        self.assertEqual(
            command + crc_bytes(command) + b"\r",
            encode_charger_source_priority(3),
        )
        for value in (-1, 4, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    encode_charger_source_priority(value)


if __name__ == "__main__":
    unittest.main()

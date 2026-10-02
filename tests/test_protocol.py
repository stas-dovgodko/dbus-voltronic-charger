import unittest

from voltronic_charger.protocol import (
    ProtocolError,
    crc_bytes,
    decode_response,
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


if __name__ == "__main__":
    unittest.main()


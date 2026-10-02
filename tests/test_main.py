import unittest

from voltronic_charger.config import ControlConfig, PowerEstimationConfig
from voltronic_charger.main import (
    _identify,
    _read_charge_current_capabilities,
    _set_charger_mode,
    _set_charge_current_limit,
    _utility_limit_for_ac_input_limit,
)
from voltronic_charger.models import ChargeCurrentCapabilities
from voltronic_charger.parser import parse_qpigs_pi30
from voltronic_charger.protocol import ProtocolError
from tests.test_parser import DOCUMENTED_SHAPE, KING_II_FIRST_CAPTURE


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.commands = []
        self.settings = []
        self.priorities = []

    def query(self, command):
        self.commands.append(command)
        response = self.responses[command]
        if isinstance(response, Exception):
            raise response
        return response

    def set_charge_current_limit(self, scope, current, parallel_unit):
        self.settings.append((scope, current, parallel_unit))

    def set_charger_source_priority(self, priority):
        self.priorities.append(priority)


class MainIdentificationTest(unittest.TestCase):
    def test_live_identity_and_qvfw2_fallback(self):
        client = FakeClient(
            {
                "QPI": "(PI30",
                "QMN": "(KING-5000",
                "QID": "(96332108100916",
                "QVFW": ProtocolError("NAK"),
                "QVFW2": "(VERFW2:00000.00",
            }
        )
        self.assertEqual(
            {
                "protocol_id": "PI30",
                "inverter_model": "KING-5000",
                "serial_number": "96332108100916",
                "firmware": "VERFW2:00000.00",
            },
            _identify(client),
        )
        self.assertEqual(["QPI", "QMN", "QID", "QVFW", "QVFW2"], client.commands)

    def test_wrong_protocol_is_rejected_before_publication(self):
        client = FakeClient({"QPI": "(PI18"})
        with self.assertRaises(ProtocolError):
            _identify(client)

    def test_wrong_model_is_rejected_before_publication(self):
        client = FakeClient({"QPI": "(PI30", "QMN": "(OTHER"})
        with self.assertRaises(ProtocolError):
            _identify(client)

    def test_charge_current_capabilities_are_queried_from_inverter(self):
        client = FakeClient(
            {
                "QPIRI": (
                    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 "
                    "42.0 56.4 54.0 2 030 140 0 2 2 9 01 0 00 48.0 0 1 120"
                ),
                "QMCHGCR": "(010 020 060 080 100 120 140",
                "QMUCHGCR": "(002 010 020 030",
            }
        )
        capabilities = _read_charge_current_capabilities(client)
        self.assertEqual(30, capabilities.utility_limit)
        self.assertEqual(140, capabilities.total_limit)
        self.assertEqual(
            ["QPIRI", "QMCHGCR", "QMUCHGCR"],
            client.commands,
        )

    def test_current_setting_is_allowlisted_and_verified_by_qpiri(self):
        client = FakeClient(
            {
                "QPIRI": (
                    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 "
                    "42.0 56.4 54.0 2 020 050 0 2 2 9 01 0 00 48.0 0 1 120"
                )
            }
        )
        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        _set_charge_current_limit(
            client,
            capabilities,
            ControlConfig(True, 0),
            "total",
            50,
        )
        self.assertEqual([("total", 50, 0)], client.settings)
        self.assertEqual(["QPIRI"], client.commands)

    def test_current_setting_accepts_integer_string_from_dbus_cli(self):
        client = FakeClient(
            {
                "QPIRI": (
                    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 "
                    "42.0 56.4 54.0 2 020 060 0 2 2 9 01 0 00 48.0 0 1 120"
                )
            }
        )
        capabilities = ChargeCurrentCapabilities(
            utility_limit=60,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30, 40, 50, 60),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        self.assertEqual(
            20,
            _set_charge_current_limit(
                client,
                capabilities,
                ControlConfig(True, 0),
                "utility",
                "20",
            ),
        )
        self.assertEqual([("utility", 20, 0)], client.settings)

    def test_current_setting_rejects_fractional_string(self):
        capabilities = ChargeCurrentCapabilities(
            utility_limit=60,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30, 40, 50, 60),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        with self.assertRaises(ProtocolError):
            _set_charge_current_limit(
                FakeClient({}),
                capabilities,
                ControlConfig(True, 0),
                "utility",
                "20.0",
            )

    def test_current_setting_rejects_value_outside_live_options_before_write(self):
        client = FakeClient({})
        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        with self.assertRaises(ProtocolError):
            _set_charge_current_limit(
                client,
                capabilities,
                ControlConfig(True, 0),
                "total",
                55,
            )
        self.assertEqual([], client.settings)

    def test_current_setting_fails_when_qpiri_does_not_confirm_it(self):
        client = FakeClient(
            {
                "QPIRI": (
                    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 "
                    "42.0 56.4 54.0 2 030 060 0 2 2 9 01 0 00 48.0 0 1 120"
                )
            }
        )
        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        with self.assertRaises(ProtocolError):
            _set_charge_current_limit(
                client,
                capabilities,
                ControlConfig(True, 0),
                "total",
                50,
            )

    def test_mode_off_uses_solar_only_and_verifies_qpiri(self):
        client = FakeClient(
            {
                "QPIRI": (
                    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 "
                    "42.0 56.4 54.0 2 030 060 0 2 3 9 01 0 00 48.0 0 1 120"
                )
            }
        )
        self.assertEqual(3, _set_charger_mode(client, 2, 2, 4))
        self.assertEqual([3], client.priorities)
        self.assertEqual(["QPIRI"], client.commands)

    def test_mode_on_requires_known_enabled_priority(self):
        client = FakeClient({})
        with self.assertRaises(ProtocolError):
            _set_charger_mode(client, 3, None, 1)
        self.assertEqual([], client.priorities)

    def test_ac_input_limit_maps_to_highest_safe_live_utility_option(self):
        status = parse_qpigs_pi30(DOCUMENTED_SHAPE)
        estimation = PowerEstimationConfig(70.0, 95.0)
        self.assertEqual(
            40,
            _utility_limit_for_ac_input_limit(
                estimation,
                status,
                (2, 10, 20, 30, 40, 50, 60),
                10.0,
            ),
        )
        self.assertEqual(
            60,
            _utility_limit_for_ac_input_limit(
                estimation,
                status,
                (2, 10, 20, 30, 40, 50, 60),
                15.0,
            ),
        )

    def test_ac_input_limit_requires_live_voltage_and_supported_floor(self):
        estimation = PowerEstimationConfig(70.0, 95.0)
        with self.assertRaises(ProtocolError):
            _utility_limit_for_ac_input_limit(
                estimation,
                parse_qpigs_pi30(KING_II_FIRST_CAPTURE),
                (2, 10, 20),
                10.0,
            )
        with self.assertRaises(ProtocolError):
            _utility_limit_for_ac_input_limit(
                estimation,
                parse_qpigs_pi30(DOCUMENTED_SHAPE),
                (10, 20),
                0.1,
            )


if __name__ == "__main__":
    unittest.main()

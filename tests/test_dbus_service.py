import os
import sys
import tempfile
import types
import unittest

from voltronic_charger.config import load_config
from voltronic_charger.dbus_service import ChargerDbusService
from voltronic_charger.models import ChargeCurrentCapabilities
from voltronic_charger.parser import parse_qpigs_pi30
from tests.test_parser import DOCUMENTED_SHAPE, KING_II_FIRST_CAPTURE


AC_ONLY_CHARGING = DOCUMENTED_SHAPE.replace("00000111", "00000001")


class FakeVeDbusService:
    def __init__(self, name, bus=None, register=None):
        self.name = name
        self.values = {}
        self.arguments = {}
        self.registered = False

    def add_path(self, path, value=None, **arguments):
        self.values[path] = value
        self.arguments[path] = arguments

    def register(self):
        self.registered = True

    def __setitem__(self, path, value):
        self.values[path] = value


def config_text(publish):
    return """[serial]
port=/dev/ttyUSB1
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

    def test_mixed_ac_and_pv_does_not_assign_total_current_to_ac_charger(self):
        service = ChargerDbusService(
            self._config(True),
            protocol_id="PI30",
            inverter_model="KING-5000",
        )
        service.publish(parse_qpigs_pi30(DOCUMENTED_SHAPE))
        values = service._service.values
        self.assertEqual(1, values["/Connected"])
        self.assertEqual(52.4, values["/Dc/0/Voltage"])
        self.assertIsNone(values["/Dc/0/Current"])
        self.assertIsNone(values["/Dc/0/Power"])
        self.assertEqual(3, values["/State"])
        self.assertEqual(0, values["/ErrorCode"])
        self.assertEqual(420, values["/Protocol/PvChargingPower"])
        self.assertIsNone(values["/Ac/In/L1/P"])
        self.assertIsNone(values["/Ac/In/L1/I"])
        self.assertEqual("PI30", values["/Protocol/Id"])
        self.assertEqual("KING-5000", values["/Protocol/Model"])

    def test_ac_only_charge_publishes_current_power_and_ac_telemetry(self):
        service = ChargerDbusService(self._config(True))
        service.publish(parse_qpigs_pi30(AC_ONLY_CHARGING))
        values = service._service.values
        self.assertEqual(12.0, values["/Dc/0/Current"])
        self.assertAlmostEqual(628.8, values["/Dc/0/Power"])
        self.assertEqual(230.0, values["/Ac/In/L1/V"])
        self.assertEqual(50.0, values["/Ac/In/L1/F"])
        self.assertAlmostEqual(70.0 + 628.8 / 0.95, values["/Ac/In/L1/P"])
        self.assertAlmostEqual(
            (70.0 + 628.8 / 0.95) / 230.0,
            values["/Ac/In/L1/I"],
        )
        self.assertEqual(230.0, values["/Ac/Out/L1/V"])
        self.assertEqual(50.0, values["/Ac/Out/L1/F"])
        self.assertEqual(400, values["/Ac/Out/L1/P"])
        self.assertEqual(500, values["/Ac/Out/L1/S"])
        self.assertEqual(10, values["/Ac/Out/L1/LoadPercentage"])
        self.assertEqual(1, values["/NrOfOutputs"])
        self.assertEqual(3, values["/State"])

    def test_real_idle_capture_publishes_zero_current_power_and_off_state(self):
        service = ChargerDbusService(self._config(True))
        service.publish(parse_qpigs_pi30(KING_II_FIRST_CAPTURE))
        values = service._service.values
        self.assertEqual(0.0, values["/Dc/0/Current"])
        self.assertEqual(0.0, values["/Dc/0/Power"])
        self.assertEqual(0.0, values["/Ac/In/L1/P"])
        self.assertEqual(0.0, values["/Ac/In/L1/I"])
        self.assertEqual(0, values["/State"])
        self.assertEqual(0, values["/Protocol/Charging"])

    def test_current_publication_can_remain_disabled(self):
        service = ChargerDbusService(self._config(False))
        service.publish(parse_qpigs_pi30(DOCUMENTED_SHAPE))
        values = service._service.values
        self.assertIsNone(values["/Dc/0/Current"])
        self.assertIsNone(values["/Dc/0/Power"])

    def test_publishes_inverter_reported_current_limits_and_options(self):
        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=140,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 60, 80, 100, 120, 140),
        )
        service = ChargerDbusService(self._config(True), capabilities=capabilities)
        values = service._service.values
        self.assertEqual(140, values["/Settings/ChargeCurrentLimit"])
        self.assertEqual(30, values["/Settings/UtilityChargeCurrentLimit"])
        self.assertEqual(
            "10,20,60,80,100,120,140",
            values["/Capabilities/ChargeCurrentLimits"],
        )
        self.assertEqual(
            "2,10,20,30",
            values["/Capabilities/UtilityChargeCurrentLimits"],
        )
        self.assertEqual(0, values["/Protocol/CurrentLimitWritesEnabled"])
        self.assertEqual(1, values["/Protocol/AcInputPowerEstimated"])
        self.assertEqual(70.0, values["/Protocol/SelfConsumptionWatts"])
        self.assertEqual(95.0, values["/Protocol/AcToDcEfficiencyPercent"])
        self.assertNotIn(
            "writeable",
            service._service.arguments["/Settings/ChargeCurrentLimit"],
        )

    def test_current_limit_paths_are_writeable_only_with_guarded_callback(self):
        calls = []

        def writer(scope, value):
            calls.append((scope, value))
            return True

        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        service = ChargerDbusService(
            self._config(True),
            capabilities=capabilities,
            current_limit_writer=writer,
        )
        arguments = service._service.arguments["/Settings/ChargeCurrentLimit"]
        self.assertTrue(arguments["writeable"])
        self.assertTrue(arguments["onchangecallback"]("unused", 50))
        self.assertEqual([("total", 50)], calls)
        self.assertEqual(1, service._service.values["/Protocol/CurrentLimitWritesEnabled"])

    def test_standard_ac_current_limit_uses_estimated_ac_amps(self):
        calls = []

        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
        )
        service = ChargerDbusService(
            self._config(True),
            capabilities=capabilities,
            ac_input_current_limit_writer=lambda value: calls.append(value) is None,
        )
        service.publish(parse_qpigs_pi30(AC_ONLY_CHARGING))
        expected = (52.4 * 30 / 0.95 + 70.0) / 230.0
        self.assertAlmostEqual(
            expected,
            service._service.values["/Ac/In/CurrentLimit"],
        )
        arguments = service._service.arguments["/Ac/In/CurrentLimit"]
        self.assertTrue(arguments["writeable"])
        self.assertTrue(arguments["onchangecallback"]("unused", 6.0))
        self.assertEqual([6.0], calls)

        service.set_charge_current_limit("utility", 20)
        expected = (52.4 * 20 / 0.95 + 70.0) / 230.0
        self.assertAlmostEqual(
            expected,
            service._service.values["/Ac/In/CurrentLimit"],
        )
        self.assertEqual(
            20,
            service._service.values["/Settings/UtilityChargeCurrentLimit"],
        )

    def test_mode_reflects_priority_and_is_writeable_only_with_callback(self):
        calls = []

        capabilities = ChargeCurrentCapabilities(
            utility_limit=30,
            total_limit=60,
            selectable_utility_limits=(2, 10, 20, 30),
            selectable_total_limits=(10, 20, 30, 40, 50, 60),
            charger_source_priority=3,
        )
        service = ChargerDbusService(
            self._config(True),
            capabilities=capabilities,
            mode_writer=lambda value: calls.append(value) is None,
        )
        self.assertEqual(4, service._service.values["/Mode"])
        arguments = service._service.arguments["/Mode"]
        self.assertTrue(arguments["writeable"])
        self.assertTrue(arguments["onchangecallback"]("unused", 1))
        self.assertEqual([1], calls)
        service.set_charger_source_priority(2)
        self.assertEqual(1, service._service.values["/Mode"])

    def test_disconnect_invalidates_live_values(self):
        service = ChargerDbusService(self._config(True))
        service.publish(parse_qpigs_pi30(DOCUMENTED_SHAPE))
        service.disconnect()
        values = service._service.values
        self.assertEqual(0, values["/Connected"])
        for path in (
            "/Dc/0/Voltage",
            "/Dc/0/Current",
            "/Dc/0/Power",
            "/Ac/In/L1/V",
            "/Ac/In/L1/I",
            "/Ac/In/L1/P",
            "/Ac/Out/L1/P",
            "/State",
        ):
            self.assertIsNone(values[path])


if __name__ == "__main__":
    unittest.main()

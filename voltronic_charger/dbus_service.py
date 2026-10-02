"""Venus charger publisher for the confirmed King II PI30 profile."""

from __future__ import annotations

import os
import platform
import sys

from . import __version__
from .config import DriverConfig
from .models import ChargeCurrentCapabilities, Pi30Status


CHARGER_MODE_ON = 1
CHARGER_MODE_OFF = 4
CHARGER_STATE_OFF = 0
CHARGER_STATE_BULK = 3


def _load_vedbus():
    velib_path = os.environ.get(
        "VELIB_PYTHON", "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
    )
    if velib_path not in sys.path:
        sys.path.insert(0, velib_path)
    try:
        from vedbus import VeDbusService
    except ImportError as exc:
        raise RuntimeError(
            "unable to import Victron velib_python from {}".format(velib_path)
        ) from exc
    return VeDbusService


def _format_value(unit: str, decimals: int):
    def formatter(_path, value):
        if value is None:
            return ""
        return ("{:0." + str(decimals) + "f} {} ").format(value, unit).strip()

    return formatter


class ChargerDbusService:
    def __init__(
        self,
        config: DriverConfig,
        serial_number=None,
        firmware=None,
        protocol_id=None,
        inverter_model=None,
        capabilities: ChargeCurrentCapabilities = None,
        current_limit_writer=None,
        ac_input_current_limit_writer=None,
        mode_writer=None,
        bus=None,
    ):
        VeDbusService = _load_vedbus()
        self.config = config
        self._last_status = None
        self._total_charge_current_limit = (
            capabilities.total_limit if capabilities is not None else None
        )
        self._utility_charge_current_limit = (
            capabilities.utility_limit if capabilities is not None else None
        )
        if bus is None:
            try:
                import dbus
            except ImportError:
                pass
            else:
                try:
                    bus = dbus.SystemBus()
                except Exception:
                    pass
        self._service = VeDbusService(
            config.device.service_name, bus=bus, register=False
        )
        self._add("/Mgmt/ProcessName", "voltronic-charger")
        self._add("/Mgmt/ProcessVersion", "Python {}".format(platform.python_version()))
        self._add("/Mgmt/Connection", "RS232 {}".format(config.serial.port))
        self._add("/DeviceInstance", config.device.device_instance)
        self._add("/ProductName", config.device.model)
        self._add("/CustomName", config.device.custom_name)
        self._add("/FirmwareVersion", firmware)
        self._add("/Serial", serial_number)
        self._add("/DriverVersion", __version__)
        self._add("/Connected", 0)
        self._add("/NrOfOutputs", 1)
        self._add("/Dc/0/Voltage", None, _format_value("V", 2))
        self._add("/Dc/0/Current", None, _format_value("A", 1))
        self._add("/Dc/0/Power", None, _format_value("W", 0))
        self._add("/Ac/In/L1/V", None, _format_value("V", 1))
        self._add("/Ac/In/L1/F", None, _format_value("Hz", 1))
        self._add("/Ac/In/L1/I", None, _format_value("A", 1))
        self._add("/Ac/In/L1/P", None, _format_value("W", 0))
        self._add(
            "/Ac/In/CurrentLimit",
            None,
            _format_value("A", 1),
            writeable=ac_input_current_limit_writer is not None,
            onchange=(
                (lambda _path, value: ac_input_current_limit_writer(value))
                if ac_input_current_limit_writer is not None
                else None
            ),
        )
        self._add("/Ac/Out/L1/V", None, _format_value("V", 1))
        self._add("/Ac/Out/L1/F", None, _format_value("Hz", 1))
        self._add("/Ac/Out/L1/P", None, _format_value("W", 0))
        self._add("/Ac/Out/L1/S", None, _format_value("VA", 0))
        self._add("/Ac/Out/L1/LoadPercentage", None, _format_value("%", 0))
        self._add("/State", None)
        self._add("/ErrorCode", None)
        initial_priority = (
            capabilities.charger_source_priority if capabilities is not None else None
        )
        self._add(
            "/Mode",
            self._mode_for_priority(initial_priority),
            writeable=mode_writer is not None,
            onchange=(lambda _path, value: mode_writer(value)) if mode_writer else None,
        )
        self._add("/Protocol/Profile", config.protocol.profile)
        self._add("/Protocol/Id", protocol_id)
        self._add("/Protocol/Model", inverter_model)
        self._add(
            "/Protocol/CurrentPublished",
            int(config.protocol.publish_battery_charging_current),
        )
        self._add("/Protocol/Charging", None)
        self._add("/Protocol/AcCharging", None)
        self._add("/Protocol/SccCharging", None)
        self._add("/Protocol/ReportedBatteryChargingCurrent", None)
        self._add("/Protocol/PvInputCurrentForBattery", None)
        self._add("/Protocol/PvChargingPower", None)
        self._add("/Protocol/AcInputPowerEstimated", 1)
        self._add(
            "/Protocol/SelfConsumptionWatts",
            config.power_estimation.self_consumption_watts,
        )
        self._add(
            "/Protocol/AcToDcEfficiencyPercent",
            config.power_estimation.ac_to_dc_efficiency_percent,
        )
        self._add(
            "/Protocol/CurrentLimitWritesEnabled",
            int(current_limit_writer is not None),
        )
        self._add("/Protocol/ModeWritesEnabled", int(mode_writer is not None))
        self._add("/Protocol/ChargerSourcePriority", initial_priority)
        if capabilities is not None:
            def total_limit_changed(_path, value):
                return current_limit_writer("total", value)

            def utility_limit_changed(_path, value):
                return current_limit_writer("utility", value)

            self._add(
                "/Settings/ChargeCurrentLimit",
                capabilities.total_limit,
                _format_value("A", 0),
                writeable=current_limit_writer is not None,
                onchange=(
                    total_limit_changed if current_limit_writer is not None else None
                ),
            )
            self._add(
                "/Settings/UtilityChargeCurrentLimit",
                capabilities.utility_limit,
                _format_value("A", 0),
                writeable=current_limit_writer is not None,
                onchange=(
                    utility_limit_changed
                    if current_limit_writer is not None
                    else None
                ),
            )
            self._add(
                "/Capabilities/ChargeCurrentLimits",
                capabilities.selectable_total_limits_text,
            )
            self._add(
                "/Capabilities/UtilityChargeCurrentLimits",
                capabilities.selectable_utility_limits_text,
            )
        self._service.register()

    def _add(
        self,
        path,
        value=None,
        formatter=None,
        writeable=False,
        onchange=None,
    ):
        arguments = {}
        if formatter is not None:
            arguments["gettextcallback"] = formatter
        if writeable:
            arguments["writeable"] = True
            arguments["onchangecallback"] = onchange
        self._service.add_path(path, value, **arguments)

    def _set(self, path, value):
        self._service[path] = value

    @staticmethod
    def _mode_for_priority(priority):
        if priority is None:
            return None
        return CHARGER_MODE_OFF if priority == 3 else CHARGER_MODE_ON

    def set_charger_source_priority(self, priority: int) -> None:
        self._set("/Protocol/ChargerSourcePriority", priority)
        self._set("/Mode", self._mode_for_priority(priority))

    def _estimate_ac_input_for_dc_current(self, dc_current, status):
        if status.grid_voltage <= 0 or status.battery_voltage <= 0:
            return None, None
        efficiency = self.config.power_estimation.ac_to_dc_efficiency_percent / 100.0
        power = (
            status.battery_voltage * dc_current / efficiency
            + self.config.power_estimation.self_consumption_watts
        )
        return power, power / status.grid_voltage

    def _estimate_ac_input(self, status):
        if status.grid_voltage <= 0 or status.grid_frequency <= 0:
            return 0.0, 0.0
        if status.ac_charging and status.scc_charging:
            return None, None
        dc_current = (
            status.reported_battery_charging_current
            if status.ac_charging
            else 0.0
        )
        return self._estimate_ac_input_for_dc_current(dc_current, status)

    def _publish_ac_input_current_limit(self, status):
        if self._utility_charge_current_limit is None:
            self._set("/Ac/In/CurrentLimit", None)
            return
        _power, current = self._estimate_ac_input_for_dc_current(
            self._utility_charge_current_limit,
            status,
        )
        self._set("/Ac/In/CurrentLimit", current)

    def set_charge_current_limit(self, scope: str, value: int) -> None:
        if scope == "total":
            self._total_charge_current_limit = value
            self._set("/Settings/ChargeCurrentLimit", value)
        elif scope == "utility":
            self._utility_charge_current_limit = value
            self._set("/Settings/UtilityChargeCurrentLimit", value)
            if self._last_status is not None:
                self._publish_ac_input_current_limit(self._last_status)
        else:
            raise ValueError("unknown charge-current limit scope: {!r}".format(scope))

    def publish(self, status: Pi30Status) -> None:
        self._last_status = status
        self._set("/Connected", 1)
        self._set("/Dc/0/Voltage", status.battery_voltage)
        self._set("/Ac/In/L1/V", status.grid_voltage)
        self._set("/Ac/In/L1/F", status.grid_frequency)
        ac_input_power, ac_input_current = self._estimate_ac_input(status)
        self._set("/Ac/In/L1/I", ac_input_current)
        self._set("/Ac/In/L1/P", ac_input_power)
        self._publish_ac_input_current_limit(status)
        self._set("/Ac/Out/L1/V", status.output_voltage)
        self._set("/Ac/Out/L1/F", status.output_frequency)
        self._set("/Ac/Out/L1/P", status.output_active_power)
        self._set("/Ac/Out/L1/S", status.output_apparent_power)
        self._set("/Ac/Out/L1/LoadPercentage", status.output_load_percent)
        self._set("/Protocol/Charging", int(status.charger_active))
        self._set("/Protocol/AcCharging", int(status.ac_charging))
        self._set("/Protocol/SccCharging", int(status.scc_charging))
        self._set(
            "/Protocol/ReportedBatteryChargingCurrent",
            status.reported_battery_charging_current,
        )
        self._set(
            "/Protocol/PvInputCurrentForBattery", status.pv_input_current_for_battery
        )
        self._set("/Protocol/PvChargingPower", status.pv_charging_power)
        if self.config.protocol.publish_battery_charging_current:
            # PI30 reports one battery charge current. It is attributable to
            # this AC charger only when AC charging is active without SCC.
            if status.ac_charging and not status.scc_charging:
                current = status.reported_battery_charging_current
                self._set("/Dc/0/Current", current)
                self._set("/Dc/0/Power", status.battery_voltage * current)
            elif not status.ac_charging:
                self._set("/Dc/0/Current", 0.0)
                self._set("/Dc/0/Power", 0.0)
            else:
                self._set("/Dc/0/Current", None)
                self._set("/Dc/0/Power", None)
        else:
            self._set("/Dc/0/Current", None)
            self._set("/Dc/0/Power", None)
        # PI30 does not expose a charge-stage name; active AC charge is shown
        # as Bulk rather than inventing Absorption or Float states.
        self._set(
            "/State",
            CHARGER_STATE_BULK if status.ac_charging else CHARGER_STATE_OFF,
        )
        self._set("/ErrorCode", 0)

    def disconnect(self) -> None:
        self._set("/Connected", 0)
        for path in (
            "/Dc/0/Voltage",
            "/Dc/0/Current",
            "/Dc/0/Power",
            "/Ac/In/L1/V",
            "/Ac/In/L1/F",
            "/Ac/In/L1/I",
            "/Ac/In/L1/P",
            "/Ac/Out/L1/V",
            "/Ac/Out/L1/F",
            "/Ac/Out/L1/P",
            "/Ac/Out/L1/S",
            "/Ac/Out/L1/LoadPercentage",
            "/State",
            "/ErrorCode",
            "/Protocol/Charging",
            "/Protocol/AcCharging",
            "/Protocol/SccCharging",
            "/Protocol/ReportedBatteryChargingCurrent",
            "/Protocol/PvInputCurrentForBattery",
            "/Protocol/PvChargingPower",
        ):
            self._set(path, None)

"""Minimal Venus charger publisher with current attribution gated off by default."""

from __future__ import annotations

import os
import platform
import sys

from . import __version__
from .config import DriverConfig
from .models import Pi30Status


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
    def __init__(self, config: DriverConfig, serial_number=None, firmware=None, bus=None):
        VeDbusService = _load_vedbus()
        self.config = config
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
        self._add("/Dc/0/Voltage", None, _format_value("V", 2))
        self._add("/Dc/0/Current", None, _format_value("A", 1))
        self._add("/Dc/0/Power", None, _format_value("W", 0))
        self._add("/State", None)
        self._add("/ErrorCode", None)
        self._add("/Protocol/Profile", config.protocol.profile)
        self._add("/Protocol/CurrentPublished", int(
            config.protocol.publish_battery_charging_current
        ))
        self._add("/Protocol/AcCharging", None)
        self._add("/Protocol/SccCharging", None)
        self._service.register()

    def _add(self, path, value=None, formatter=None):
        arguments = {}
        if formatter is not None:
            arguments["gettextcallback"] = formatter
        self._service.add_path(path, value, **arguments)

    def _set(self, path, value):
        self._service[path] = value

    def publish(self, status: Pi30Status) -> None:
        self._set("/Connected", 1)
        self._set("/Dc/0/Voltage", status.battery_voltage)
        self._set("/Protocol/AcCharging", int(status.ac_charging))
        self._set("/Protocol/SccCharging", int(status.scc_charging))
        # Current attribution is not validated for the target King II firmware.
        # Keep both paths invalid even though the raw QPIGS token is retained in
        # the parsed diagnostic model.
        self._set("/Dc/0/Current", None)
        self._set("/Dc/0/Power", None)
        # Do not invent a Victron charge stage from PI30 source flags.
        self._set("/State", None)
        self._set("/ErrorCode", None)

    def disconnect(self) -> None:
        self._set("/Connected", 0)
        for path in (
            "/Dc/0/Voltage",
            "/Dc/0/Current",
            "/Dc/0/Power",
            "/State",
            "/ErrorCode",
            "/Protocol/AcCharging",
            "/Protocol/SccCharging",
        ):
            self._set(path, None)

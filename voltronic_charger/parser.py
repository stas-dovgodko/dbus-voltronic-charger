"""Strict parsers for explicitly selected candidate protocol profiles."""

from __future__ import annotations

import re
from typing import Tuple

from .models import ChargeCurrentCapabilities, Pi30Status
from .protocol import ProtocolError


_BINARY_RE = re.compile(r"^[01]+$")


def parse_protocol_id(payload: str) -> str:
    if not payload.startswith("(") or len(payload) < 2:
        raise ProtocolError("invalid protocol identity response")
    value = payload[1:].strip()
    if not value or not re.match(r"^[A-Za-z0-9._-]+$", value):
        raise ProtocolError("invalid protocol identity value")
    return value


def parse_text_response(payload: str) -> str:
    if not payload.startswith("("):
        raise ProtocolError("response payload does not start with '('")
    value = payload[1:].strip()
    if value == "NAK":
        raise ProtocolError("inverter rejected or does not support the inquiry")
    return value


def parse_charge_current_options(payload: str) -> Tuple[int, ...]:
    """Parse an inverter-provided selectable current list without assumptions."""

    value = parse_text_response(payload)
    fields = value.split()
    if not fields:
        raise ProtocolError("charge-current option list is empty")
    options = []
    for field in fields:
        if not field.isdigit():
            raise ProtocolError(
                "invalid charge-current option: {!r}".format(field)
            )
        current = int(field)
        if current not in options:
            options.append(current)
    return tuple(options)


def parse_qpiri_charge_limits(payload: str) -> Tuple[int, int]:
    """Return current utility and total charge limits from PI30 QPIRI."""

    if not payload.startswith("("):
        raise ProtocolError("QPIRI response does not start with '('")
    fields = payload[1:].split()
    if len(fields) < 15:
        raise ProtocolError(
            "PI30 QPIRI requires at least 15 fields; received {}".format(len(fields))
        )
    for index, name in (
        (13, "utility charge-current limit"),
        (14, "total charge-current limit"),
    ):
        if not fields[index].isdigit():
            raise ProtocolError("invalid {}: {!r}".format(name, fields[index]))
    return int(fields[13]), int(fields[14])


def parse_qpiri_charger_source_priority(payload: str) -> int:
    """Return the configured PI30 charger-source priority."""

    if not payload.startswith("("):
        raise ProtocolError("QPIRI response does not start with '('")
    fields = payload[1:].split()
    if len(fields) < 18:
        raise ProtocolError(
            "PI30 QPIRI requires at least 18 fields; received {}".format(len(fields))
        )
    if not fields[17].isdigit():
        raise ProtocolError(
            "invalid charger-source priority: {!r}".format(fields[17])
        )
    priority = int(fields[17])
    if priority not in (0, 1, 2, 3):
        raise ProtocolError(
            "unsupported charger-source priority: {}".format(priority)
        )
    return priority


def build_charge_current_capabilities(
    qpiri_payload: str,
    total_options_payload: str,
    utility_options_payload: str,
) -> ChargeCurrentCapabilities:
    """Build capabilities exclusively from values returned by the inverter."""

    utility_limit, total_limit = parse_qpiri_charge_limits(qpiri_payload)
    return ChargeCurrentCapabilities(
        utility_limit=utility_limit,
        total_limit=total_limit,
        selectable_utility_limits=parse_charge_current_options(
            utility_options_payload
        ),
        selectable_total_limits=parse_charge_current_options(total_options_payload),
        charger_source_priority=parse_qpiri_charger_source_priority(qpiri_payload),
    )


def _number(value: str, conversion, name: str):
    try:
        return conversion(value)
    except ValueError as exc:
        raise ProtocolError("invalid {}: {!r}".format(name, value)) from exc


def _bits(value: str, width: int, name: str) -> str:
    if len(value) != width or _BINARY_RE.match(value) is None:
        raise ProtocolError("{} must be exactly {} binary digits".format(name, width))
    return value


def parse_qpigs_pi30(payload: str) -> Pi30Status:
    """Parse the documented classic PI30 QPIGS layout.

    This parser must not be auto-selected merely from the inverter model name.
    The caller has to select the `pi30` profile after live identification.
    """

    if not payload.startswith("("):
        raise ProtocolError("QPIGS response does not start with '('")
    fields = payload[1:].split()
    if len(fields) != 21:
        raise ProtocolError(
            "PI30 QPIGS requires exactly 21 fields; received {}".format(len(fields))
        )

    return Pi30Status(
        grid_voltage=_number(fields[0], float, "grid voltage"),
        grid_frequency=_number(fields[1], float, "grid frequency"),
        output_voltage=_number(fields[2], float, "output voltage"),
        output_frequency=_number(fields[3], float, "output frequency"),
        output_apparent_power=_number(fields[4], int, "output apparent power"),
        output_active_power=_number(fields[5], int, "output active power"),
        output_load_percent=_number(fields[6], int, "output load percent"),
        bus_voltage=_number(fields[7], int, "bus voltage"),
        battery_voltage=_number(fields[8], float, "battery voltage"),
        reported_battery_charging_current=_number(
            fields[9], float, "reported battery charging current"
        ),
        battery_capacity_percent=_number(fields[10], int, "battery capacity"),
        heatsink_temperature=_number(fields[11], float, "heatsink temperature"),
        pv_input_current_for_battery=_number(
            fields[12], float, "PV input current for battery"
        ),
        pv_input_voltage=_number(fields[13], float, "PV input voltage"),
        scc_battery_voltage=_number(fields[14], float, "SCC battery voltage"),
        battery_discharge_current=_number(fields[15], float, "battery discharge current"),
        status_bits=_bits(fields[16], 8, "status bits"),
        battery_voltage_offset_10mv=_number(fields[17], int, "battery voltage offset"),
        eeprom_version=_number(fields[18], int, "EEPROM version"),
        pv_charging_power=_number(fields[19], int, "PV charging power"),
        extended_status_bits=_bits(fields[20], 3, "extended status bits"),
    )

"""Typed telemetry values with deliberately narrow semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Union


JsonScalar = Union[str, float, int, bool]


@dataclass(frozen=True)
class Pi30Status:
    """Classic 21-token QPIGS response from the candidate PI30 profile.

    `reported_battery_charging_current` is named conservatively: it records the
    protocol field without claiming AC-only, PV-only, or total attribution for
    the King II 5000.
    """

    grid_voltage: float
    grid_frequency: float
    output_voltage: float
    output_frequency: float
    output_apparent_power: int
    output_active_power: int
    output_load_percent: int
    bus_voltage: int
    battery_voltage: float
    reported_battery_charging_current: float
    battery_capacity_percent: int
    heatsink_temperature: float
    pv_input_current_for_battery: float
    pv_input_voltage: float
    scc_battery_voltage: float
    battery_discharge_current: float
    status_bits: str
    battery_voltage_offset_10mv: int
    eeprom_version: int
    pv_charging_power: int
    extended_status_bits: str

    @property
    def ac_charging(self) -> bool:
        return self.status_bits[7] == "1"

    @property
    def scc_charging(self) -> bool:
        return self.status_bits[6] == "1"

    @property
    def charging(self) -> bool:
        return self.status_bits[5] == "1"

    def as_dict(self) -> Dict[str, JsonScalar]:
        values = asdict(self)
        values.update(
            ac_charging=self.ac_charging,
            scc_charging=self.scc_charging,
            charging=self.charging,
        )
        return values


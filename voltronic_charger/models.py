"""Typed telemetry values with deliberately narrow semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Tuple, Union


JsonScalar = Union[str, float, int, bool]


@dataclass(frozen=True)
class ChargeCurrentCapabilities:
    """Charge-current settings and choices reported by the inverter."""

    utility_limit: int
    total_limit: int
    selectable_utility_limits: Tuple[int, ...]
    selectable_total_limits: Tuple[int, ...]
    charger_source_priority: int = 2

    @property
    def selectable_utility_limits_text(self) -> str:
        return ",".join(str(value) for value in self.selectable_utility_limits)

    @property
    def selectable_total_limits_text(self) -> str:
        return ",".join(str(value) for value in self.selectable_total_limits)


@dataclass(frozen=True)
class Pi30Status:
    """Classic 21-token QPIGS response from a compatible PI30 device."""

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

    @property
    def charger_active(self) -> bool:
        return (
            self.charging
            or self.ac_charging
            or self.scc_charging
            or self.reported_battery_charging_current > 0
        )

    def as_dict(self) -> Dict[str, JsonScalar]:
        values = asdict(self)
        values.update(
            ac_charging=self.ac_charging,
            scc_charging=self.scc_charging,
            charging=self.charging,
            charger_active=self.charger_active,
        )
        return values

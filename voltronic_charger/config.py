"""Configuration with fail-closed protocol and serial defaults."""

from __future__ import annotations

import configparser
import math
import re
from dataclasses import dataclass
from typing import Optional


_SERVICE_RE = re.compile(r"^com\.victronenergy\.charger\.[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int
    timeout: float
    command_delay: float


@dataclass(frozen=True)
class ProtocolConfig:
    profile: str
    publish_battery_charging_current: bool


@dataclass(frozen=True)
class DeviceConfig:
    model: str
    custom_name: str
    device_instance: int
    service_name: str


@dataclass(frozen=True)
class ControlConfig:
    allow_current_limit_writes: bool
    parallel_unit: int
    utility_current_format: str = "auto"
    allow_mode_writes: bool = False
    enabled_charger_source_priority: Optional[int] = None


@dataclass(frozen=True)
class PowerEstimationConfig:
    self_consumption_watts: float
    ac_to_dc_efficiency_percent: float


@dataclass(frozen=True)
class DriverConfig:
    serial: SerialConfig
    protocol: ProtocolConfig
    device: DeviceConfig
    control: ControlConfig
    power_estimation: PowerEstimationConfig
    poll_interval: float
    failure_threshold: int
    log_level: str


def load_config(path: str) -> DriverConfig:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise ValueError("configuration file not found: {}".format(path))

    serial_section = parser["serial"]
    protocol_section = parser["protocol"]
    device_section = parser["device"]
    driver_section = parser["driver"]
    control_section = parser["control"] if parser.has_section("control") else None
    estimation_section = (
        parser["power_estimation"]
        if parser.has_section("power_estimation")
        else None
    )

    device_instance_text = device_section.get("device_instance", "").strip()
    if not device_instance_text:
        raise ValueError("device.device_instance must be explicitly configured")
    try:
        device_instance = int(device_instance_text)
    except ValueError as exc:
        raise ValueError("device.device_instance must be an integer") from exc

    config = DriverConfig(
        serial=SerialConfig(
            port=serial_section.get("port", "").strip(),
            baudrate=serial_section.getint("baudrate", 2400),
            timeout=serial_section.getfloat("timeout", 2.0),
            command_delay=serial_section.getfloat("command_delay", 0.5),
        ),
        protocol=ProtocolConfig(
            profile=protocol_section.get("profile", "unconfirmed").strip().lower(),
            publish_battery_charging_current=protocol_section.getboolean(
                "publish_battery_charging_current", False
            ),
        ),
        device=DeviceConfig(
            model=device_section.get("model", "Voltronic PI30 Charger").strip(),
            custom_name=device_section.get(
                "custom_name", "Voltronic PI30 Charger"
            ).strip(),
            device_instance=device_instance,
            service_name=device_section.get(
                "service_name", "com.victronenergy.charger.voltronic_pi30"
            ).strip(),
        ),
        control=ControlConfig(
            allow_current_limit_writes=(
                control_section.getboolean("allow_current_limit_writes", False)
                if control_section is not None
                else False
            ),
            parallel_unit=(
                control_section.getint("parallel_unit", 0)
                if control_section is not None
                else 0
            ),
            utility_current_format=(
                control_section.get("utility_current_format", "auto").strip().lower()
                if control_section is not None
                else "auto"
            ),
            allow_mode_writes=(
                control_section.getboolean("allow_mode_writes", False)
                if control_section is not None
                else False
            ),
            enabled_charger_source_priority=(
                int(control_section.get("enabled_charger_source_priority"))
                if control_section is not None
                and control_section.get(
                    "enabled_charger_source_priority", ""
                ).strip()
                else None
            ),
        ),
        power_estimation=PowerEstimationConfig(
            self_consumption_watts=(
                estimation_section.getfloat("self_consumption_watts", 70.0)
                if estimation_section is not None
                else 70.0
            ),
            ac_to_dc_efficiency_percent=(
                estimation_section.getfloat(
                    "ac_to_dc_efficiency_percent", 95.0
                )
                if estimation_section is not None
                else 95.0
            ),
        ),
        poll_interval=driver_section.getfloat("poll_interval", 5.0),
        failure_threshold=driver_section.getint("failure_threshold", 3),
        log_level=driver_section.get("log_level", "INFO").strip().upper(),
    )

    if not config.serial.port:
        raise ValueError("serial.port must be an explicit device path")
    if config.serial.baudrate <= 0:
        raise ValueError("serial.baudrate must be positive")
    if config.serial.timeout <= 0:
        raise ValueError("serial.timeout must be positive")
    if config.serial.command_delay < 0:
        raise ValueError("serial.command_delay cannot be negative")
    if config.protocol.profile not in {"unconfirmed", "pi30"}:
        raise ValueError("protocol.profile must be unconfirmed or pi30")
    if not config.device.model:
        raise ValueError("device.model must not be empty")
    if not config.device.custom_name:
        raise ValueError("device.custom_name must not be empty")
    if config.device.device_instance < 0:
        raise ValueError("device.device_instance cannot be negative")
    if not _SERVICE_RE.match(config.device.service_name):
        raise ValueError(
            "device.service_name must use com.victronenergy.charger.<safe_suffix>"
        )
    if config.control.parallel_unit < 0 or config.control.parallel_unit > 9:
        raise ValueError("control.parallel_unit must be between 0 and 9")
    if config.control.utility_current_format not in {
        "auto",
        "standard",
        "parallel",
    }:
        raise ValueError(
            "control.utility_current_format must be auto, standard, or parallel"
        )
    if (
        config.control.enabled_charger_source_priority is not None
        and config.control.enabled_charger_source_priority not in (0, 1, 2)
    ):
        raise ValueError(
            "control.enabled_charger_source_priority must be 0, 1, or 2"
        )
    if (
        not math.isfinite(config.power_estimation.self_consumption_watts)
        or config.power_estimation.self_consumption_watts < 0
    ):
        raise ValueError(
            "power_estimation.self_consumption_watts must be finite and non-negative"
        )
    if (
        not math.isfinite(config.power_estimation.ac_to_dc_efficiency_percent)
        or config.power_estimation.ac_to_dc_efficiency_percent <= 0
        or config.power_estimation.ac_to_dc_efficiency_percent > 100
    ):
        raise ValueError(
            "power_estimation.ac_to_dc_efficiency_percent must be greater than 0 and at most 100"
        )
    if config.poll_interval <= 0:
        raise ValueError("driver.poll_interval must be positive")
    if config.failure_threshold < 1:
        raise ValueError("driver.failure_threshold must be at least 1")
    return config

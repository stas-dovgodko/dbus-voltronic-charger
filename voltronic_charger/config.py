"""Configuration with fail-closed protocol and serial defaults."""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass


_SERVICE_RE = re.compile(r"^com\.victronenergy\.charger\.[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int
    timeout: float


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
class DriverConfig:
    serial: SerialConfig
    protocol: ProtocolConfig
    device: DeviceConfig
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
        ),
        protocol=ProtocolConfig(
            profile=protocol_section.get("profile", "unconfirmed").strip().lower(),
            publish_battery_charging_current=protocol_section.getboolean(
                "publish_battery_charging_current", False
            ),
        ),
        device=DeviceConfig(
            model=device_section.get("model", "Voltronic King II 5000").strip(),
            custom_name=device_section.get(
                "custom_name", "Voltronic King II 5000"
            ).strip(),
            device_instance=device_instance,
            service_name=device_section.get(
                "service_name", "com.victronenergy.charger.voltronic_king2"
            ).strip(),
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
    if config.protocol.profile not in {"unconfirmed", "pi30"}:
        raise ValueError("protocol.profile must be unconfirmed or pi30")
    if config.protocol.publish_battery_charging_current:
        raise ValueError(
            "current publication is disabled in this release until King II "
            "charging-current semantics are validated"
        )
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
    if config.poll_interval <= 0:
        raise ValueError("driver.poll_interval must be positive")
    if config.failure_threshold < 1:
        raise ValueError("driver.failure_threshold must be at least 1")
    return config

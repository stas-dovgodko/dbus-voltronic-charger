"""One-shot parser and Venus D-Bus loop for compatible PI30 devices."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sys

from .config import load_config
from .parser import (
    build_charge_current_capabilities,
    parse_qpiri_charger_source_priority,
    parse_qpiri_charge_limits,
    parse_protocol_id,
    parse_qpigs_pi30,
    parse_text_response,
)
from .protocol import ProtocolError
from .serial_client import SerialQueryClient


LOGGER = logging.getLogger("voltronic-charger")
EXPECTED_PROTOCOL = "PI30"


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description="Voltronic Venus charger bridge")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.ini"),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read and parse one QPIGS response without connecting to D-Bus",
    )
    return parser.parse_args(argv)


def _read_status(client):
    return parse_qpigs_pi30(client.query("QPIGS"))


def _identify(client):
    protocol_id = parse_protocol_id(client.query("QPI"))
    if protocol_id != EXPECTED_PROTOCOL:
        raise ProtocolError(
            "expected protocol {}, received {}".format(EXPECTED_PROTOCOL, protocol_id)
        )
    values = {"protocol_id": protocol_id}
    try:
        values["inverter_model"] = parse_text_response(client.query("QMN"))
    except Exception as exc:
        LOGGER.warning("QMN inquiry unavailable: %s", exc)
    try:
        values["serial_number"] = parse_text_response(client.query("QID"))
    except Exception as exc:
        LOGGER.warning("QID inquiry unavailable: %s", exc)

    for command in ("QVFW", "QVFW2"):
        try:
            values["firmware"] = parse_text_response(client.query(command))
            break
        except Exception as exc:
            LOGGER.warning("%s inquiry unavailable: %s", command, exc)
    return values


def _read_charge_current_capabilities(client):
    return build_charge_current_capabilities(
        client.query("QPIRI"),
        client.query("QMCHGCR"),
        client.query("QMUCHGCR"),
    )


def _read_available_charge_current_capabilities(client, required=False):
    try:
        return _read_charge_current_capabilities(client)
    except Exception as exc:
        if required:
            raise ProtocolError(
                "charge-current capabilities are required when controls are enabled"
            ) from exc
        LOGGER.warning("charge-current capabilities unavailable: %s", exc)
        return None


def _set_charge_current_limit(client, capabilities, control, scope, value):
    if isinstance(value, bool):
        raise ProtocolError("charge-current limit must be an integer")
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ProtocolError("charge-current limit must be an exact integer")
        requested = int(text)
    else:
        try:
            requested = int(value)
        except (TypeError, ValueError) as exc:
            raise ProtocolError("charge-current limit must be an integer") from exc
        if requested != value:
            raise ProtocolError("charge-current limit must be an exact integer")

    if scope == "total":
        allowed = capabilities.selectable_total_limits
    elif scope == "utility":
        allowed = capabilities.selectable_utility_limits
    else:
        raise ProtocolError("unknown charge-current limit scope: {!r}".format(scope))
    if requested not in allowed:
        raise ProtocolError(
            "{} A is not in the inverter-reported {} limit list: {}".format(
                requested, scope, ",".join(str(item) for item in allowed)
            )
        )

    client.set_charge_current_limit(
        scope,
        requested,
        control.parallel_unit,
        control.utility_current_format,
    )
    utility_limit, total_limit = parse_qpiri_charge_limits(client.query("QPIRI"))
    verified = total_limit if scope == "total" else utility_limit
    if verified != requested:
        raise ProtocolError(
            "{} charge-current verification failed: requested {} A, read back {} A".format(
                scope, requested, verified
            )
        )
    return verified


def _utility_limit_for_ac_input_limit(
    power_estimation,
    status,
    selectable_utility_limits,
    value,
):
    if isinstance(value, bool):
        raise ProtocolError("AC input current limit must be numeric")
    try:
        requested = float(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("AC input current limit must be numeric") from exc
    if not math.isfinite(requested) or requested <= 0:
        raise ProtocolError("AC input current limit must be finite and positive")
    if status.grid_voltage <= 0 or status.battery_voltage <= 0:
        raise ProtocolError(
            "cannot convert AC input limit without live grid and battery voltage"
        )

    efficiency = power_estimation.ac_to_dc_efficiency_percent / 100.0
    dc_budget = (
        max(
            0.0,
            requested * status.grid_voltage
            - power_estimation.self_consumption_watts,
        )
        * efficiency
        / status.battery_voltage
    )
    allowed = [
        limit
        for limit in selectable_utility_limits
        if limit <= dc_budget + 1e-9
    ]
    if not allowed:
        raise ProtocolError(
            "{} A AC is below the minimum inverter-reported utility charge limit".format(
                requested
            )
        )
    return max(allowed)


def _set_charger_mode(client, current_priority, enabled_priority, mode):
    if isinstance(mode, bool) or not isinstance(mode, int):
        raise ProtocolError("charger mode must be an integer")
    if mode == 4:
        target_priority = 3
    elif mode == 1:
        if current_priority != 3:
            target_priority = current_priority
        elif enabled_priority is not None:
            target_priority = enabled_priority
        else:
            raise ProtocolError(
                "cannot enable utility charging without a remembered or configured priority"
            )
    else:
        raise ProtocolError("charger mode must be 1 (on) or 4 (off)")

    if target_priority == current_priority:
        return target_priority
    client.set_charger_source_priority(target_priority)
    verified = parse_qpiri_charger_source_priority(client.query("QPIRI"))
    if verified != target_priority:
        raise ProtocolError(
            "charger mode verification failed: requested priority {}, read back {}".format(
                target_priority, verified
            )
        )
    return verified


class _RuntimeController:
    """Keep one D-Bus service alive while the serial device disconnects."""

    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.service = None
        self.connected = False
        self.failures = 0
        self.latest_status = None
        self.capabilities = None
        self.current_priority = None
        self.enabled_priority = config.control.enabled_charger_source_priority

    def attach_service(self, service):
        self.service = service

    def _controls_require_capabilities(self):
        return (
            self.config.control.allow_current_limit_writes
            or self.config.control.allow_mode_writes
        )

    def _read_reconnect_snapshot(self):
        identity = _identify(self.client)
        status = _read_status(self.client)
        capabilities = _read_available_charge_current_capabilities(
            self.client,
            required=self._controls_require_capabilities(),
        )
        return identity, status, capabilities

    def poll(self):
        reconnecting = not self.connected
        try:
            if reconnecting:
                identity, status, capabilities = self._read_reconnect_snapshot()
                self.capabilities = capabilities
                self.current_priority = (
                    capabilities.charger_source_priority
                    if capabilities is not None
                    else None
                )
                if (
                    self.enabled_priority is None
                    and self.current_priority is not None
                    and self.current_priority != 3
                ):
                    self.enabled_priority = self.current_priority
                if self.service is not None:
                    self.service.set_identity(**identity)
                    self.service.set_capabilities(capabilities)
            else:
                status = _read_status(self.client)

            self.latest_status = status
            if self.service is not None:
                self.service.publish(status)
            if reconnecting:
                LOGGER.info("inverter connection established")
            self.connected = True
            self.failures = 0
        except Exception as exc:
            self.failures += 1
            self.client.close()
            if self.connected and self.failures >= self.config.failure_threshold:
                self.connected = False
                if self.service is not None:
                    self.service.disconnect()
                LOGGER.warning(
                    "inverter disconnected after %d consecutive failures: %s; "
                    "continuing reconnect attempts",
                    self.failures,
                    exc,
                )
            elif self.connected:
                LOGGER.warning(
                    "poll failed (%d/%d): %s",
                    self.failures,
                    self.config.failure_threshold,
                    exc,
                )
            elif self.failures == 1:
                LOGGER.warning(
                    "inverter unavailable: %s; continuing reconnect attempts",
                    exc,
                )
            else:
                LOGGER.debug("reconnect attempt failed: %s", exc)
        return True

    def current_limit_writer(self, scope, value):
        if not self.connected or self.capabilities is None:
            LOGGER.warning(
                "refused %s charge-current update while inverter is disconnected",
                scope,
            )
            return False
        try:
            verified = _set_charge_current_limit(
                self.client,
                self.capabilities,
                self.config.control,
                scope,
                value,
            )
        except Exception:
            LOGGER.exception(
                "refused or failed %s charge-current update to %r A",
                scope,
                value,
            )
            return False
        if self.service is not None:
            self.service.set_charge_current_limit(scope, verified)
        LOGGER.info("verified %s charge-current limit at %s A", scope, verified)
        return True

    def ac_input_current_limit_writer(self, value):
        if (
            not self.connected
            or self.capabilities is None
            or self.latest_status is None
        ):
            LOGGER.warning(
                "refused AC input current limit update while inverter is disconnected"
            )
            return False
        try:
            utility_limit = _utility_limit_for_ac_input_limit(
                self.config.power_estimation,
                self.latest_status,
                self.capabilities.selectable_utility_limits,
                value,
            )
        except Exception:
            LOGGER.exception("refused AC input current limit update to %r A", value)
            return False
        return self.current_limit_writer("utility", utility_limit)

    def mode_writer(self, value):
        if not self.connected or self.capabilities is None:
            LOGGER.warning("refused charger mode update while inverter is disconnected")
            return False
        if self.current_priority != 3:
            self.enabled_priority = self.current_priority
        try:
            self.current_priority = _set_charger_mode(
                self.client,
                self.current_priority,
                self.enabled_priority,
                value,
            )
        except Exception:
            LOGGER.exception("refused or failed charger mode update to %r", value)
            return False
        if self.current_priority != 3:
            self.enabled_priority = self.current_priority
        if self.service is not None:
            self.service.set_charger_source_priority(self.current_priority)
        LOGGER.info(
            "verified charger mode at %s using source priority %s",
            value,
            self.current_priority,
        )
        return True


def _run(config) -> int:
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    from .dbus_service import ChargerDbusService

    client = SerialQueryClient(
        config.serial.port,
        config.serial.baudrate,
        config.serial.timeout,
        config.serial.command_delay,
    )
    DBusGMainLoop(set_as_default=True)
    controller = _RuntimeController(client, config)
    current_limit_writer = (
        controller.current_limit_writer
        if config.control.allow_current_limit_writes
        else None
    )
    ac_input_current_limit_writer = (
        controller.ac_input_current_limit_writer
        if config.control.allow_current_limit_writes
        else None
    )
    mode_writer = controller.mode_writer if config.control.allow_mode_writes else None
    service = ChargerDbusService(
        config,
        capabilities=None,
        current_limit_writer=current_limit_writer,
        ac_input_current_limit_writer=ac_input_current_limit_writer,
        mode_writer=mode_writer,
    )
    controller.attach_service(service)
    mainloop = GLib.MainLoop()

    def stop(_signum, _frame):
        client.close()
        mainloop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    controller.poll()
    GLib.timeout_add(int(config.poll_interval * 1000), controller.poll)
    mainloop.run()
    client.close()
    return 0


def main(argv=None) -> int:
    args = _arguments(argv)
    try:
        config = load_config(args.config)
    except Exception as exc:
        print("Configuration error: {}".format(exc), file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if config.protocol.profile != "pi30":
        print(
            "Refusing to parse or publish: protocol.profile is unconfirmed. "
            "Run the inquiry-only probe first.",
            file=sys.stderr,
        )
        return 2
    client = SerialQueryClient(
        config.serial.port,
        config.serial.baudrate,
        config.serial.timeout,
        config.serial.command_delay,
    )
    if args.once:
        try:
            identity = _identify(client)
            status = _read_status(client)
            capabilities = _read_available_charge_current_capabilities(
                client,
                required=(
                    config.control.allow_current_limit_writes
                    or config.control.allow_mode_writes
                ),
            )
            output = {
                "identity": identity,
                "charge_current_capabilities": (
                    {
                        "charger_source_priority": (
                            capabilities.charger_source_priority
                        ),
                        "utility_limit": capabilities.utility_limit,
                        "total_limit": capabilities.total_limit,
                        "selectable_utility_limits": list(
                            capabilities.selectable_utility_limits
                        ),
                        "selectable_total_limits": list(
                            capabilities.selectable_total_limits
                        ),
                    }
                    if capabilities is not None
                    else None
                ),
                "status": status.as_dict(),
            }
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0
        finally:
            client.close()
    return _run(config)


if __name__ == "__main__":
    raise SystemExit(main())

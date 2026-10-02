"""One-shot parser and Venus D-Bus loop for the confirmed King II profile."""

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
EXPECTED_MODEL = "KING-5000"


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
    inverter_model = parse_text_response(client.query("QMN"))
    if inverter_model != EXPECTED_MODEL:
        raise ProtocolError(
            "expected model {}, received {}".format(EXPECTED_MODEL, inverter_model)
        )

    values = {"protocol_id": protocol_id, "inverter_model": inverter_model}
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

    client.set_charge_current_limit(scope, requested, control.parallel_unit)
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
    identity = _identify(client)
    capabilities = _read_charge_current_capabilities(client)
    initial = _read_status(client)
    latest_status = [initial]
    DBusGMainLoop(set_as_default=True)

    service = None
    current_limit_writer = None
    if config.control.allow_current_limit_writes:
        def current_limit_writer(scope, value):
            try:
                verified = _set_charge_current_limit(
                    client, capabilities, config.control, scope, value
                )
            except Exception:
                LOGGER.exception(
                    "refused or failed %s charge-current update to %r A",
                    scope,
                    value,
                )
                return False
            if service is not None:
                service.set_charge_current_limit(scope, verified)
            LOGGER.info("verified %s charge-current limit at %s A", scope, verified)
            return True

    ac_input_current_limit_writer = None
    if current_limit_writer is not None:
        def ac_input_current_limit_writer(value):
            try:
                utility_limit = _utility_limit_for_ac_input_limit(
                    config.power_estimation,
                    latest_status[0],
                    capabilities.selectable_utility_limits,
                    value,
                )
            except Exception:
                LOGGER.exception(
                    "refused AC input current limit update to %r A",
                    value,
                )
                return False
            return current_limit_writer("utility", utility_limit)

    current_priority = capabilities.charger_source_priority
    enabled_priority = config.control.enabled_charger_source_priority
    if enabled_priority is None and current_priority != 3:
        enabled_priority = current_priority
    mode_writer = None
    if config.control.allow_mode_writes:
        def mode_writer(value):
            nonlocal current_priority, enabled_priority
            if current_priority != 3:
                enabled_priority = current_priority
            try:
                current_priority = _set_charger_mode(
                    client,
                    current_priority,
                    enabled_priority,
                    value,
                )
            except Exception:
                LOGGER.exception("refused or failed charger mode update to %r", value)
                return False
            if current_priority != 3:
                enabled_priority = current_priority
            if service is not None:
                service.set_charger_source_priority(current_priority)
            LOGGER.info(
                "verified charger mode at %s using source priority %s",
                value,
                current_priority,
            )
            return True

    service = ChargerDbusService(
        config,
        capabilities=capabilities,
        current_limit_writer=current_limit_writer,
        ac_input_current_limit_writer=ac_input_current_limit_writer,
        mode_writer=mode_writer,
        **identity
    )
    service.publish(initial)
    failures = 0
    mainloop = GLib.MainLoop()

    def poll():
        nonlocal failures
        try:
            status = _read_status(client)
            latest_status[0] = status
            service.publish(status)
            failures = 0
        except Exception:
            failures += 1
            LOGGER.exception("poll failed (%d/%d)", failures, config.failure_threshold)
            client.close()
            if failures >= config.failure_threshold:
                service.disconnect()
                mainloop.quit()
                return False
        return True

    def stop(_signum, _frame):
        client.close()
        mainloop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    GLib.timeout_add(int(config.poll_interval * 1000), poll)
    mainloop.run()
    client.close()
    return 1 if failures >= config.failure_threshold else 0


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
            capabilities = _read_charge_current_capabilities(client)
            output = {
                "identity": identity,
                "charge_current_capabilities": {
                    "charger_source_priority": capabilities.charger_source_priority,
                    "utility_limit": capabilities.utility_limit,
                    "total_limit": capabilities.total_limit,
                    "selectable_utility_limits": list(
                        capabilities.selectable_utility_limits
                    ),
                    "selectable_total_limits": list(
                        capabilities.selectable_total_limits
                    ),
                },
                "status": _read_status(client).as_dict(),
            }
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0
        finally:
            client.close()
    return _run(config)


if __name__ == "__main__":
    raise SystemExit(main())

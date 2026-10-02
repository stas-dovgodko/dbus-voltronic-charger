"""One-shot parser and Venus D-Bus loop for an explicitly confirmed profile."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys

from .config import load_config
from .parser import parse_qpigs_pi30, parse_text_response
from .serial_client import SerialQueryClient


LOGGER = logging.getLogger("voltronic-charger")


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Voltronic Venus charger bridge")
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
    values = {}
    for command, name in (("QID", "serial"), ("QVFW", "firmware")):
        try:
            values[name] = parse_text_response(client.query(command))
        except Exception as exc:
            LOGGER.warning("%s inquiry unavailable: %s", command, exc)
    return values


def _run(config) -> int:
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    from .dbus_service import ChargerDbusService

    client = SerialQueryClient(
        config.serial.port, config.serial.baudrate, config.serial.timeout
    )
    identity = _identify(client)
    initial = _read_status(client)
    DBusGMainLoop(set_as_default=True)
    service = ChargerDbusService(config, **identity)
    service.publish(initial)
    failures = 0
    mainloop = GLib.MainLoop()

    def poll():
        nonlocal failures
        try:
            service.publish(_read_status(client))
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
        config.serial.port, config.serial.baudrate, config.serial.timeout
    )
    if args.once:
        try:
            print(json.dumps(_read_status(client).as_dict(), indent=2, sort_keys=True))
            return 0
        finally:
            client.close()
    return _run(config)


if __name__ == "__main__":
    raise SystemExit(main())


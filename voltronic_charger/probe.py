"""Inquiry-only serial probe; does not connect to D-Bus."""

from __future__ import annotations

import argparse
import json
import sys

from .parser import parse_protocol_id, parse_qpigs_pi30, parse_text_response
from .protocol import READ_ONLY_COMMANDS
from .serial_client import SerialQueryClient


DEFAULT_COMMANDS = ("QPI", "QMN", "QID", "QVFW", "QVFW2", "QPIGS", "QMOD")


def _arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Send only allowlisted read-only inquiries to a Voltronic inverter"
    )
    parser.add_argument("--port", required=True, help="Explicit serial device path")
    parser.add_argument("--baudrate", type=int, default=2400)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--command",
        action="append",
        choices=sorted(READ_ONLY_COMMANDS),
        help="Inquiry to send; repeat for multiple commands",
    )
    parser.add_argument(
        "--profile",
        choices=("unconfirmed", "pi30"),
        default="unconfirmed",
        help="Parse QPIGS only when pi30 is explicitly selected",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _arguments(argv)
    commands = tuple(args.command or DEFAULT_COMMANDS)
    results = []
    client = SerialQueryClient(args.port, args.baudrate, args.timeout)
    try:
        for command in commands:
            record = {"command": command}
            try:
                raw = client.query_raw(command)
                record["raw_hex"] = raw.hex()
                from .protocol import decode_response

                payload = decode_response(raw)
                record["payload"] = payload
                if command == "QPI":
                    record["protocol_id"] = parse_protocol_id(payload)
                elif command == "QPIGS" and args.profile == "pi30":
                    record["parsed"] = parse_qpigs_pi30(payload).as_dict()
                else:
                    record["value"] = parse_text_response(payload)
                record["ok"] = True
            except Exception as exc:
                record["ok"] = False
                record["error"] = "{}: {}".format(type(exc).__name__, exc)
            results.append(record)
    finally:
        client.close()
    print(json.dumps({"port": args.port, "baudrate": args.baudrate, "results": results}, indent=2))
    return 0 if any(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())


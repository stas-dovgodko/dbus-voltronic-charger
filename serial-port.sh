#!/bin/sh
set -eu

APP_DIR="/data/apps/dbus-voltronic-charger"
CONFIG="$APP_DIR/config.ini"
ACTION="${1:-}"

case "$ACTION" in
    acquire)
        HELPER="/opt/victronenergy/serial-starter/stop-tty.sh"
        ;;
    release)
        HELPER="/opt/victronenergy/serial-starter/start-tty.sh"
        ;;
    *)
        echo "Usage: $0 acquire|release" >&2
        exit 2
        ;;
esac

if [ ! -x "$HELPER" ]; then
    echo "Missing Venus serial-starter helper: $HELPER" >&2
    exit 1
fi

DEVICE=$(
    PYTHONPATH="$APP_DIR" /usr/bin/python3 -c '
import os
import sys
from voltronic_charger.config import load_config

port = load_config(sys.argv[1]).serial.port
resolved = os.path.realpath(port)
if not resolved.startswith("/dev/"):
    raise SystemExit("serial.port must resolve below /dev: {}".format(port))
print(os.path.basename(resolved))
' "$CONFIG"
)

case "$DEVICE" in
    ttyUSB*|ttyACM*|ttyS*)
        ;;
    *)
        echo "Refusing unsupported serial device basename: $DEVICE" >&2
        exit 1
        ;;
esac

"$HELPER" "$DEVICE" &
helper_pid=$!

(
    sleep 15
    if kill -0 "$helper_pid" 2>/dev/null; then
        echo "serial-starter helper timed out for $DEVICE" >&2
        kill "$helper_pid" 2>/dev/null || true
        sleep 1
        kill -9 "$helper_pid" 2>/dev/null || true
    fi
) &
watchdog_pid=$!

if wait "$helper_pid"; then
    helper_rc=0
else
    helper_rc=$?
fi

kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true

if [ "$helper_rc" -ne 0 ]; then
    echo "serial-starter helper failed for $DEVICE with status $helper_rc" >&2
    exit "$helper_rc"
fi

echo "Serial port $DEVICE: $ACTION complete"

#!/bin/sh
set -eu

APP_NAME="dbus-voltronic-charger"
APP_DIR="/data/apps/$APP_NAME"
SERVICE_DIR="$APP_DIR/service"
SERVICE_LINK="/service/$APP_NAME"
CONFIG="$APP_DIR/config.ini"
RC_LOCAL="/data/rc.local"
BOOT_HOOK="ln -s $SERVICE_DIR $SERVICE_LINK 2>/dev/null || true"
VELIB_PYTHON="/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"

if [ "${1:-}" != "--confirm-pi30" ] || [ "$#" -ne 1 ]; then
    echo "Usage: $0 --confirm-pi30" >&2
    echo "Run only after a CRC-valid probe confirms the classic 21-field PI30 layout." >&2
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this activation script as root." >&2
    exit 1
fi

for command in svc svstat multilog; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required Venus command is missing: $command" >&2
        exit 1
    fi
done

if [ ! -x /usr/bin/python3 ]; then
    echo "/usr/bin/python3 is missing." >&2
    exit 1
fi
if ! /usr/bin/python3 -c 'import serial, dbus, gi' >/dev/null 2>&1; then
    echo "Python serial/dbus/gi modules are not all available on this Venus release." >&2
    exit 1
fi
if [ ! -f "$VELIB_PYTHON/vedbus.py" ]; then
    echo "Victron velib_python was not found at $VELIB_PYTHON" >&2
    echo "Stop and report the installed Venus OS release; activation was not changed." >&2
    exit 1
fi
if [ ! -f "$CONFIG" ]; then
    echo "Missing configuration: $CONFIG" >&2
    exit 1
fi

PYTHONPATH="$APP_DIR" /usr/bin/python3 -c '
import sys
from voltronic_charger.config import load_config
c = load_config(sys.argv[1])
if c.protocol.profile != "pi30":
    raise SystemExit("protocol.profile must be pi30 before activation")
print("Validated port={}, instance={}, current_published={}".format(
    c.serial.port, c.device.device_instance,
    c.protocol.publish_battery_charging_current))
' "$CONFIG"

if [ -e "$SERVICE_LINK" ] || [ -L "$SERVICE_LINK" ]; then
    if [ ! -L "$SERVICE_LINK" ]; then
        echo "Foreign non-symlink service path exists: $SERVICE_LINK" >&2
        exit 1
    fi
    actual=$(readlink -f "$SERVICE_LINK" 2>/dev/null || true)
    expected=$(readlink -f "$SERVICE_DIR" 2>/dev/null || true)
    if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
        echo "Foreign service symlink exists; refusing to replace it: $SERVICE_LINK" >&2
        exit 1
    fi
else
    ln -s "$SERVICE_DIR" "$SERVICE_LINK"
fi

if [ ! -f "$RC_LOCAL" ]; then
    printf '%s\n' '#!/bin/sh' > "$RC_LOCAL"
fi
if ! grep -Fqx "$BOOT_HOOK" "$RC_LOCAL"; then
    printf '%s\n' "$BOOT_HOOK" >> "$RC_LOCAL"
fi
chmod 755 "$RC_LOCAL"

rm -f "$SERVICE_DIR/down"
svc -u "$SERVICE_LINK"
echo "Activated $SERVICE_LINK"
echo "No serial-starter rules or other services were changed."
echo "Check: svstat $SERVICE_LINK"
echo "Logs: tail -f /var/log/$APP_NAME/current"


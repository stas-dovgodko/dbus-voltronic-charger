#!/bin/sh
set -eu

APP_NAME="dbus-voltronic-charger"
APP_DIR="/data/apps/$APP_NAME"
SERVICE_LINK="/service/$APP_NAME"
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root on the Cerbo." >&2
    exit 1
fi

if [ ! -x /usr/bin/python3 ]; then
    echo "/usr/bin/python3 is required; this Venus OS image is not compatible." >&2
    exit 1
fi

if ! /usr/bin/python3 -c 'import serial' >/dev/null 2>&1; then
    echo "Python module 'serial' (pyserial) is missing." >&2
    echo "No package installation was attempted. Stop and report the Venus OS version." >&2
    exit 1
fi

is_owned_service_link() {
    [ -L "$SERVICE_LINK" ] || return 1
    actual=$(readlink -f "$SERVICE_LINK" 2>/dev/null || true)
    expected=$(readlink -f "$APP_DIR/service" 2>/dev/null || true)
    [ -n "$expected" ] && [ "$actual" = "$expected" ]
}

if [ -e "$SERVICE_LINK" ] || [ -L "$SERVICE_LINK" ]; then
    if is_owned_service_link; then
        echo "Service is installed. Run $APP_DIR/deactivate.sh before updating." >&2
    else
        echo "Foreign service path exists; refusing to touch it: $SERVICE_LINK" >&2
    fi
    exit 1
fi

if [ "$SOURCE_DIR" != "$APP_DIR" ]; then
    if [ -d "$APP_DIR" ]; then
        backup="${APP_DIR}.backup.$(date +%Y%m%d-%H%M%S).$$"
        cp -R "$APP_DIR" "$backup"
        echo "Existing installation backed up to $backup"
    fi

    mkdir -p "$APP_DIR/voltronic_charger" "$APP_DIR/tests" \
        "$APP_DIR/service/log"
    for file in "$SOURCE_DIR"/voltronic_charger/*.py; do
        cp "$file" "$APP_DIR/voltronic_charger/"
    done
    for file in "$SOURCE_DIR"/tests/*.py; do
        cp "$file" "$APP_DIR/tests/"
    done
    cp "$SOURCE_DIR/README.md" "$APP_DIR/README.md"
    cp "$SOURCE_DIR/LICENSE" "$APP_DIR/LICENSE"
    cp "$SOURCE_DIR/pyproject.toml" "$APP_DIR/pyproject.toml"
    cp "$SOURCE_DIR/config.ini.example" "$APP_DIR/config.ini.example"
    cp "$SOURCE_DIR/install.sh" "$APP_DIR/install.sh"
    cp "$SOURCE_DIR/activate.sh" "$APP_DIR/activate.sh"
    cp "$SOURCE_DIR/deactivate.sh" "$APP_DIR/deactivate.sh"
    cp "$SOURCE_DIR/uninstall.sh" "$APP_DIR/uninstall.sh"
    cp "$SOURCE_DIR/service/run" "$APP_DIR/service/run"
    cp "$SOURCE_DIR/service/log/run" "$APP_DIR/service/log/run"
fi

if [ ! -f "$APP_DIR/config.ini" ]; then
    cp "$APP_DIR/config.ini.example" "$APP_DIR/config.ini"
    echo "Created $APP_DIR/config.ini"
else
    echo "Preserved existing $APP_DIR/config.ini"
fi

chmod 755 "$APP_DIR/install.sh" "$APP_DIR/activate.sh" \
    "$APP_DIR/deactivate.sh" "$APP_DIR/uninstall.sh" \
    "$APP_DIR/service/run" "$APP_DIR/service/log/run"
touch "$APP_DIR/service/down"

echo "Installed files under $APP_DIR"
echo "The service is NOT active and no serial-starter configuration was changed."
echo "Next: edit config.ini, run the inquiry-only probe, and validate the protocol."


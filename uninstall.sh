#!/bin/sh
set -eu

APP_NAME="dbus-voltronic-charger"
APP_DIR="/data/apps/$APP_NAME"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this uninstaller as root." >&2
    exit 1
fi
if [ ! -d "$APP_DIR" ]; then
    echo "$APP_DIR is not installed."
    exit 0
fi

"$APP_DIR/deactivate.sh"
backup="${APP_DIR}.removed.$(date +%Y%m%d-%H%M%S).$$"
mv "$APP_DIR" "$backup"
echo "Uninstalled without deletion. Files and config were moved to:"
echo "$backup"
echo "Rollback: mv '$backup' '$APP_DIR'"


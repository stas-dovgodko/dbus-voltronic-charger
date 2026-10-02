#!/bin/sh
set -eu

APP_NAME="dbus-voltronic-charger"
APP_DIR="/data/apps/$APP_NAME"
SERVICE_DIR="$APP_DIR/service"
SERVICE_LINK="/service/$APP_NAME"
RC_LOCAL="/data/rc.local"
BOOT_HOOK="ln -s $SERVICE_DIR $SERVICE_LINK 2>/dev/null || true"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this deactivation script as root." >&2
    exit 1
fi

if [ ! -d "$APP_DIR" ]; then
    echo "$APP_DIR is not installed."
    exit 0
fi

mkdir -p "$SERVICE_DIR"
touch "$SERVICE_DIR/down"

if [ -L "$SERVICE_LINK" ]; then
    actual=$(readlink -f "$SERVICE_LINK" 2>/dev/null || true)
    expected=$(readlink -f "$SERVICE_DIR" 2>/dev/null || true)
    if [ -n "$expected" ] && [ "$actual" = "$expected" ]; then
        if command -v svc >/dev/null 2>&1; then
            svc -d "$SERVICE_LINK" 2>/dev/null || true
        fi
        rm -f "$SERVICE_LINK"
    else
        echo "Leaving foreign service symlink untouched: $SERVICE_LINK" >&2
    fi
elif [ -e "$SERVICE_LINK" ]; then
    echo "Leaving foreign non-symlink path untouched: $SERVICE_LINK" >&2
fi

if [ -f "$RC_LOCAL" ] && grep -Fqx "$BOOT_HOOK" "$RC_LOCAL"; then
    temporary="$RC_LOCAL.dbus-voltronic-charger.$$"
    grep -Fvx "$BOOT_HOOK" "$RC_LOCAL" > "$temporary" || true
    mv "$temporary" "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
fi

echo "Deactivated $APP_NAME; application files and config were preserved."
echo "No other service or serial-starter state was changed."

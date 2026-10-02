# Voltronic King II 5000 charger telemetry for Venus OS

This project is an **early, read-only foundation** for reading a Voltronic
King II 5000 inverter over serial and eventually exposing its verified battery
charging output as an additional `com.victronenergy.charger` device on a
Victron Cerbo / Venus OS system.

The probe and driver can transmit only an explicit allowlist of inquiry
commands. The included Cerbo installer is staged: it installs files but does
not activate the service, alter serial-starter, or claim a serial port.

## Cerbo installation and first test

These instructions assume a Venus OS image that has `/usr/bin/python3`, the
Python `serial`, `dbus`, and `gi` modules, Victron `velib_python`, runit tools,
`wget`, and `unzip`. The installer verifies the runtime pieces it needs and
stops if they are missing. The exact Cerbo hardware and installed Venus release
have not yet been supplied, so compatibility is not promised for every image.

Before installation, record the runtime:

```sh
cat /opt/victronenergy/version
uname -m
/usr/bin/python3 --version
/usr/bin/python3 -c 'import serial; print(serial.__version__)'
```

Download without assuming Git is installed:

```sh
cd /data
wget -O dbus-voltronic-charger-main.zip \
  https://github.com/stas-dovgodko/dbus-voltronic-charger/archive/refs/heads/main.zip
unzip dbus-voltronic-charger-main.zip
cd dbus-voltronic-charger-main
chmod +x install.sh activate.sh deactivate.sh uninstall.sh
./install.sh
```

This creates `/data/apps/dbus-voltronic-charger/config.ini` and leaves a
`service/down` marker. It does not create an active service link. On an update,
an existing inactive installation is copied to a timestamped backup first and
its `config.ini` is preserved.

Review the two unresolved configuration items:

```sh
vi /data/apps/dbus-voltronic-charger/config.ini
```

- `port = /dev/ttyUSB1` is the user's current working Voltronic port. It stays
  configurable; use a verified `by-id` or `by-path` link when available.
- `device_instance` is intentionally blank. Select an unused charger-class
  device instance from the live Cerbo before activation.
- Leave `profile = unconfirmed` and current publication disabled for the first
  probe.

Make sure another process is not holding the chosen port. These commands are
read-only; availability varies by Venus image:

```sh
fuser /dev/ttyUSB1 2>/dev/null || true
ls -l /service | grep -E 'ttyUSB1|voltronic' || true
```

Run the inquiry-only capture from the installed files:

```sh
cd /data/apps/dbus-voltronic-charger
PYTHONPATH=. /usr/bin/python3 -m voltronic_charger.probe \
  --port /dev/ttyUSB1 --baudrate 2400 \
  --command QPI --command QMN --command QID --command QVFW \
  --command QVFW2 --command QPIGS --command QMOD \
  | tee king2-probe.json
```

Each successful item includes the complete response as `raw_hex`. Keep and
share `king2-probe.json` for validation. If 2400 baud returns no CRC-valid
responses, stop; do not enable the service or try setting commands.

### Staged D-Bus activation

Only when the capture confirms the classic PI30 identity and exact 21-field
`QPIGS` shape, edit `config.ini` and set `profile = pi30`. Fill the unused
`device_instance`, but keep
`publish_battery_charging_current = false`. Then test one parse without D-Bus:

```sh
cd /data/apps/dbus-voltronic-charger
PYTHONPATH=. /usr/bin/python3 -m voltronic_charger.main \
  --config ./config.ini --once
```

If that succeeds, explicitly activate:

```sh
./activate.sh --confirm-pi30
svstat /service/dbus-voltronic-charger
tail -f /var/log/dbus-voltronic-charger/current
```

Activation refuses an unconfirmed profile, missing device instance, missing
runtime dependency, or a foreign `/service/dbus-voltronic-charger` path. It
adds only this service's exact boot hook to `/data/rc.local`; it does not stop,
restart, configure, or delete serial-starter or another driver.

With current publication disabled, the D-Bus service is useful for integration
and voltage/connection testing but contributes no charger current or power to
Venus totals. This release rejects configurations that enable current
publication. A later code update can lift that gate only after the King II
field is validated under AC-only, PV-only, combined, and idle conditions.

### Stop, uninstall, and rollback

Stop the service while preserving all files and configuration:

```sh
/data/apps/dbus-voltronic-charger/deactivate.sh
```

Uninstall recoverably:

```sh
/data/apps/dbus-voltronic-charger/uninstall.sh
```

The uninstaller removes only an owned service link and this project's exact
boot-hook line, then moves the whole application directory to a timestamped
`.removed.*` backup. It prints the exact `mv` command for rollback. It does not
recursively delete files, follow symlink targets, or change another driver.

## Current safety state

- Exact target: **Voltronic King II 5000** (user-confirmed model name).
- Exact hardware revision, firmware, protocol identifier, and response layout:
  **not yet confirmed**.
- The two working Cerbo USB adapters are a PL2303 (`067b:2303`) and a
  CH340/CH341-family device (`1a86:7523`). Which adapter is connected to this
  inverter is unknown.
- No `ttyUSB0` assumption is made. The user's current Voltronic connection is
  `/dev/ttyUSB1`; `serial.port` remains configurable and may instead use an
  observed `/dev/serial/by-id/...` or `/dev/serial/by-path/...` link.
- `protocol.profile` defaults to `unconfirmed`; the D-Bus driver refuses to
  start in that state.
- `publish_battery_charging_current` defaults to `false`. Voltage can be
  displayed after the PI30 profile is confirmed, but current and power remain
  invalid (`None`) and therefore do not enter Venus charger totals.
- No charge stage is inferred. The PI30 status bits indicate charging sources,
  not a trustworthy Bulk/Absorption/Float stage, so `/State` stays invalid.

## Evidence and remaining assumption

The closest primary protocol source located is Voltronic's official
**AXPERT KS&MKS&V Communication Protocol** (2017). It specifies:

- RS-232 at 2400 baud, 8 data bits, no parity, 1 stop bit;
- command/response framing as payload + two CRC bytes + carriage return;
- read-only inquiries including `QID`, `QVFW`, `QPIGS`, `QMOD`, and `QPIWS`;
- the classic 21-token `QPIGS` response, including battery voltage and a field
  described as "battery charging current".

Source:
<https://ftps.voltronic.com.tw/E/Easunpower-93CB312922AC474787C6/RS232%20%E9%80%9A%E8%A8%8A%E5%8D%94%E8%AD%B0(communication%20protocol)/Axpert%20KS&MKS&V%20RS232%20Protocol-C(20170821).pdf>

That document does **not** name the King II 5000. The `pi30` parser in this
repository is consequently a candidate profile, not a declaration that every
King II 5000 uses that exact layout. A CRC-valid live capture is required.

For Venus OS, Victron's D-Bus API requires product services on the system bus,
SI units, a unique device instance within a class, and serial product-service
names such as `com.victronenergy.charger.<unique suffix>`:
<https://github.com/victronenergy/venus/wiki/dbus-api>

Victron's own `dbus-systemcalc-py` reads charger output 0 voltage and current,
then adds `voltage * current` to `/Dc/Charger/Power`:
<https://github.com/victronenergy/dbus-systemcalc-py/blob/master/dbus_systemcalc.py>

Victron's published Modbus mapping documents the charger paths used here:
`/Dc/0/Voltage`, `/Dc/0/Current`, `/State`, and `/ErrorCode`:
<https://github.com/victronenergy/dbus_modbustcp/blob/master/attributes.csv>

## Read-only identification on the Cerbo

First identify the physical adapter without stopping services or changing any
configuration:

```sh
ls -l /dev/serial/by-id/ 2>/dev/null
for d in /dev/ttyUSB*; do
  echo "=== $d ==="
  udevadm info --query=property --name="$d" | grep -E '^(ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|ID_PATH)='
done
```

Correlate the cable physically (unplug/replug only if operationally safe) and
record the stable `/dev/serial/by-id/...` link. Neither adapter ID proves which
device is the inverter.

Create a local environment on a normal development machine and run tests:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e . pytest
python3 -m pytest
```

The standalone probe requires Python 3.8 or newer plus `pyserial>=3.4`. From the project
root, verify the dependency without opening a serial port:

```sh
python3 -c 'import serial; print(serial.__version__)'
```

Then, on a system with the inverter serial cable available, run this exact
read-only capture using the currently confirmed port:

```sh
python3 -m voltronic_charger.probe --port /dev/ttyUSB1 --baudrate 2400 \
  --command QPI --command QMN --command QID --command QVFW \
  --command QVFW2 --command QPIGS --command QMOD | tee king2-probe.json
```

The probe prints JSON with decoded payloads and each complete wire response in
the `raw_hex` field; `tee` also saves that same output to `king2-probe.json` for
protocol validation. It does not send any setting command. A stable path can be
substituted later without code changes, for example:

```sh
python3 -m voltronic_charger.probe \
  --port /dev/serial/by-id/REPLACE_WITH_OBSERVED_LINK \
  --baudrate 2400 --command QPI --command QPIGS | tee king2-probe.json
```

If 2400 baud yields no valid frame, stop and preserve the observation; do not
cycle through random write protocols.

## Enabling the candidate profile (not deployment)

Only after the live data shows a protocol identity compatible with PI30 and an
exact 21-token `QPIGS` response matching the documented field shapes:

1. Copy `config.ini.example` to `config.ini`.
2. Keep `/dev/ttyUSB1` while it is the confirmed current port, or replace
   `serial.port` with an observed stable `by-id`/`by-path` link.
3. Set `protocol.profile = pi30`.
4. Keep `publish_battery_charging_current = false` until the current field is
   compared against the inverter display and charging sources.
5. Run `python3 -m voltronic_charger.main --config config.ini --once` offline
   from service management to inspect one parsed sample.

The D-Bus process mode and staged Cerbo tooling are included, but activation is
separate from installation and remains blocked until PI30 is confirmed.

## Why current is gated

The candidate PI30 layout calls token 10 "battery charging current" and also
publishes PV-specific values and AC/SCC charging flags. That does not by itself
prove whether the exact King II firmware reports total charge current, one
charger's contribution, a rounded value, or a value with model-specific
semantics. Publishing it prematurely as `/Dc/0/Current` would alter Venus
system totals. This release rejects `true` for the current-publication option
and always leaves `/Dc/0/Current` and `/Dc/0/Power` invalid.

## Concrete input still needed

- The stable `/dev/serial/by-id/...` or `by-path/...` link and its VID:PID for
  the inverter. The current working node is `/dev/ttyUSB1`.
- Raw JSON output from the inquiry-only probe above.
- Exact King II label details (full type code/hardware revision) and firmware
  returned by `QVFW`/`QVFW2`.
- Installed Venus OS version (`cat /opt/victronenergy/version`) and architecture
  (`uname -m`) before any later packaging or service work.
- An unused `com.victronenergy.charger` device instance from the live Cerbo;
  the example deliberately leaves `device_instance` blank.
- A comparison of reported QPIGS current with the front panel while AC-only,
  PV-only, combined charging, and idle, if those operating states can be
  observed safely.

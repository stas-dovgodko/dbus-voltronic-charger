# dbus-voltronic-charger

Venus OS driver for exposing a compatible Voltronic PI30 inverter/charger as
an additional `com.victronenergy.charger` service on a Cerbo GX.

The driver publishes battery-side charger telemetry, AC input/output data,
charger state, errors and guarded current/mode controls. Setting commands are
disabled by default and must be explicitly enabled in `config.ini`.

## Venus OS integration

The Voltronic charger appears alongside the native Victron inverter/chargers.
These screenshots show the tested King II 5000 installation:

![Voltronic King II in the Venus OS device list](docs/images/venus-device-list.png)

The device page exposes the standard charger switch and AC input-current limit.
This live capture shows `49.60 V`, `20.0 A` DC charging, an estimated `4.9 A`
AC input current and no active error:

![Voltronic King II charger details in Venus OS](docs/images/venus-voltronic-charger.png)

## Compatibility

Runtime compatibility is based on protocol responses, not a hard-coded model
name. The driver requires:

- `QPI=PI30`;
- a CRC-valid classic 21-field `QPIGS` response accepted by the strict parser;
- 2400 baud, 8N1 serial communication.

`QMN`, `QID` and firmware inquiries are optional identity metadata. A missing
or different `QMN` value does not block telemetry. Current and Mode controls
additionally require valid `QPIRI`, `QMCHGCR` and `QMUCHGCR` responses; when
those are unavailable and controls are disabled, telemetry can still run.

## Tested hardware

- Inverter: Voltronic King II 5000.
- Protocol identity: `PI30`.
- Model response: `KING-5000`.
- Serial speed: 2400 baud, 8N1.
- Venus OS: v3.80 on Cerbo GX.
- Application directory: `/data/apps/dbus-voltronic-charger`.
- Configured inverter port: `/dev/ttyUSB1`.
- Tested adapter: CH340/CH341, VID:PID `1a86:7523`.

The serial port is mandatory configuration. The driver never guesses another
port and its lifecycle scripts operate only on the configured tty. In the
confirmed installation, Pylontech remains on `/dev/ttyUSB0` and is not touched.

## D-Bus data model

The default service name is
`com.victronenergy.charger.voltronic_pi30`.

Standard charger paths include:

- `/Connected`, `/DeviceInstance`, `/ProductName`, `/CustomName`;
- `/Dc/0/Voltage`, `/Dc/0/Current`, `/Dc/0/Power`;
- `/State`, `/Mode`, `/ErrorCode`, `/NrOfOutputs`;
- `/Ac/In/L1/V`, `/Ac/In/L1/F`, `/Ac/In/L1/I`, `/Ac/In/L1/P`;
- `/Ac/In/CurrentLimit`;
- `/Ac/Out/L1/V`, `/Ac/Out/L1/F`, `/Ac/Out/L1/P`, `/Ac/Out/L1/S`;
- `/Ac/Out/L1/LoadPercentage`.

Driver-specific paths include:

- `/Settings/ChargeCurrentLimit`: total DC charging-current limit;
- `/Settings/UtilityChargeCurrentLimit`: utility charger DC-current limit;
- `/Capabilities/ChargeCurrentLimits`: live `QMCHGCR` choices;
- `/Capabilities/UtilityChargeCurrentLimits`: live `QMUCHGCR` choices;
- `/Protocol/*`: identity, source flags, raw charging values and diagnostics.

The D-Bus service remains registered when the inverter is switched off. After
the configured number of consecutive read failures it publishes
`/Connected=0`, invalidates live measurements and continues reconnect attempts
at `poll_interval`. When the inverter returns, the same process revalidates
`QPI`, `QPIGS` and the available control capabilities before publishing live
values again. Control writes are refused while disconnected.

`/State` is `3` while AC charging is active and `0` otherwise. PI30 does not
provide enough information to claim specific Absorption or Float states.

### Current and power attribution

QPIGS reports one battery charging-current value. The driver publishes it as
the AC charger's `/Dc/0/Current` only during AC-only charging and calculates
`/Dc/0/Power` once as battery voltage multiplied by current.

PV charging power remains under `/Protocol/PvChargingPower`; it is not added to
the standard charger power. During simultaneous AC and SCC charging, standard
DC current and power are invalidated because PI30 cannot split the two sources
reliably. This avoids fabricated values and double counting.

### Estimated AC input

Classic 21-field PI30 QPIGS does not report measured AC input current or power.
For AC-only charging the driver estimates them as:

```text
AC input power = battery voltage * DC charge current / efficiency + self consumption
AC input current = AC input power / AC input voltage
```

The defaults are 70 W self-consumption and 95% efficiency. Both are
configurable. `/Protocol/AcInputPowerEstimated=1` marks these values as
estimated. AC output load is deliberately not added to the charger estimate.

### Current control

The inverter supplies its valid DC current choices through `QMCHGCR` and
`QMUCHGCR`; the driver does not hard-code them. Every write must use a live
choice, receive `(ACK`, and match the following `QPIRI` read-back.

The standard `/Ac/In/CurrentLimit` uses AC amperes. The driver converts it to a
DC utility-charger budget using live AC and battery voltage, configured
efficiency and self-consumption, then selects the highest live `QMUCHGCR`
choice that does not exceed that budget.

For an exact battery-side limit, write the DC extension directly:

```sh
dbus -y com.victronenergy.charger.voltronic_pi30 \
  /Settings/UtilityChargeCurrentLimit SetValue 20
```

PI30 families use two observed utility-current command forms:
`MUCHGCnnn` and `MUCHGCmnnn`, where `m` is the parallel unit. With
`utility_current_format=auto`, the driver first tries the standard form and,
only after a valid `(NAK`, tries the parallel form and caches the accepted
variant. The confirmed King II accepted `MUCHGC0020` and reported 20.0 A after
read-back verification. The format can also be fixed explicitly to `standard`
or `parallel` in the configuration.

`/Settings/ChargeCurrentLimit` is the total AC+PV charging limit. The inverter
enforces both settings, so actual utility charging cannot exceed either one.

### Mode control

`/Mode` follows the charger convention `1=On`, `4=Off`. Off selects charger
source priority `3` (solar only). Before switching Off, the driver remembers
the current enabled priority and restores it on the next On command.

`enabled_charger_source_priority` is only a restart fallback. It is used when
the service starts while the inverter is already in priority `3`, so there is
no earlier enabled value to restore. Set `0` for utility first, `1` for solar
first, or `2` for solar and utility. Leave it empty to reject an ambiguous On
request instead of guessing. The tested King II confirmed Off to priority 3
and On back to priority 2 with QPIRI read-back.

## Configuration

Start from `config.ini.example`. The essential settings are:

```ini
[serial]
port = /dev/ttyUSB1
baudrate = 2400
timeout = 2.0
command_delay = 0.5

[protocol]
profile = pi30
publish_battery_charging_current = true

[power_estimation]
self_consumption_watts = 70
ac_to_dc_efficiency_percent = 95

[control]
allow_current_limit_writes = false
parallel_unit = 0
utility_current_format = auto
allow_mode_writes = false
enabled_charger_source_priority =

[device]
model = Voltronic PI30 Charger
custom_name = Voltronic PI30 Charger
device_instance =
service_name = com.victronenergy.charger.voltronic_pi30
```

Choose an unused charger-class `device_instance` before activation:

```sh
dbus -y | grep 'com.victronenergy.charger' || true
dbus -y SERVICE_NAME /DeviceInstance GetValue
```

Set `allow_current_limit_writes=true` and `allow_mode_writes=true` only when
remote control is intentional. Existing installations retain their configured
product/custom/service names because `install.sh` preserves `config.ini`.

## Fresh installation on Cerbo

Download and extract the packaged release:

```sh
cd /data
wget -O dbus-voltronic-charger-0.7.1.tar.gz \
  https://raw.githubusercontent.com/stas-dovgodko/dbus-voltronic-charger/main/dist/dbus-voltronic-charger-0.7.1.tar.gz
tar -xzf dbus-voltronic-charger-0.7.1.tar.gz
cd dbus-voltronic-charger-0.7.1
chmod +x install.sh activate.sh deactivate.sh uninstall.sh serial-port.sh
./install.sh
```

The installer copies the application to `/data/apps/dbus-voltronic-charger`,
preserves an existing `config.ini`, and leaves the service inactive.

Edit the installed configuration and run the inquiry/read-back check:

```sh
vi /data/apps/dbus-voltronic-charger/config.ini
cd /data/apps/dbus-voltronic-charger
PYTHONPATH=. /usr/bin/python3 -m voltronic_charger.main \
  --config ./config.ini --once
```

Activate only after the one-shot output identifies `PI30` and prints a valid
parsed status object:

```sh
./activate.sh --confirm-pi30
sleep 8
svstat /service/dbus-voltronic-charger
tail -n 30 /var/log/dbus-voltronic-charger/current
```

## Updating

The installer intentionally refuses to overwrite an active service. Deactivate
the installed version first, then run the new installer:

```sh
cd /data/apps/dbus-voltronic-charger
./deactivate.sh

cd /data/dbus-voltronic-charger-0.7.1
./install.sh

cd /data/apps/dbus-voltronic-charger
./activate.sh --confirm-pi30
sleep 8
dbus -y com.victronenergy.charger.voltronic_pi30 /DriverVersion GetValue
```

The installer creates a timestamped backup and preserves `config.ini`.

## Serial ownership

Before each start, `serial-port.sh acquire` resolves the configured path to its
tty basename and calls Venus `stop-tty.sh` for that tty only. Venus OS v3.80
does not provide `timeout`, so the project uses a bounded POSIX-shell watchdog.
It does not stop global `serial-starter` or target another USB adapter.

Deactivation releases the same configured tty through `start-tty.sh`:

```sh
/data/apps/dbus-voltronic-charger/deactivate.sh
```

Recoverable uninstall:

```sh
/data/apps/dbus-voltronic-charger/uninstall.sh
```

The uninstaller moves the application to a timestamped `.removed.*` directory
instead of recursively deleting it.

## Verification and development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q voltronic_charger
sh -n install.sh activate.sh deactivate.sh uninstall.sh serial-port.sh \
  service/run service/log/run
```

The test suite covers protocol framing, generic PI30 identity handling, the
live King II response, dynamic
current capabilities, guarded writes, ACK/NAK handling, QPIRI verification,
mode control, serial pacing, AC/DC publication, mixed-source protection and
packaging safety.

## Known limits

- AC input current and power are estimates, not measurements.
- AC+SCC charging cannot be split with the confirmed 21-field QPIGS response.
- `/Ac/In/CurrentLimit` is a charger-only AC budget; it does not include loads
  supplied through the inverter AC output.
- The runtime requires `PI30` and the supported classic 21-field QPIGS shape;
  other PI30 response layouts need a separate parser profile.

See [HANDOFF.md](HANDOFF.md) for captured protocol evidence and remaining live
validation notes.

# Development handoff

## Target and repository state

- Tested device: Voltronic King II 5000 on Venus OS v3.80 / Cerbo GX.
- Supported profile: compatible Voltronic PI30 devices with the strict classic
  21-field QPIGS shape; model name is not a runtime gate.
- D-Bus class: `com.victronenergy.charger`.
- Cerbo application: `/data/apps/dbus-voltronic-charger`.
- Serial port: required configuration, currently `/dev/ttyUSB1`.
- Inverter adapter: CH340/CH341 `1a86:7523`.
- Pylontech: separate PL2303 adapter on `/dev/ttyUSB0`; never target it.
- Current package version: `0.7.0`.

## Serial conflict resolution

The first probe had truncated replies because Venus services also held
`/dev/ttyUSB1`. On Venus OS v3.80 the scoped command is:

```sh
/opt/victronenergy/serial-starter/stop-tty.sh ttyUSB1
```

That script removes only `/dev/serial-starter/ttyUSB1` and stops services whose
name matches that tty. The image has no `timeout` binary, so `serial-port.sh`
wraps the matching `stop-tty.sh`/`start-tty.sh` call in a 15-second POSIX-shell
watchdog. It derives the tty from `serial.port`; no Pylontech port is embedded.

After the scoped stop, `fuser /dev/ttyUSB1` reported no owner, the ttyUSB1
services were down, and clean protocol frames were obtained.

## Confirmed protocol evidence

- `QPI`: `PI30`.
- `QMN`: `KING-5000`.
- `QID`: `96332108100916`.
- `QVFW`: protocol-valid `NAK`.
- `QVFW2`: `VERFW2:00000.00`.
- `QMOD`: `B` during the first capture.
- `QPIGS`: repeated CRC-valid classic 21-field responses.

First clean idle sample:

```text
(000.0 00.0 229.9 50.0 0002 0002 000 365 52.50 000 073 0043 0000 000.0 00.00 00000 00010000 00 00 00000 010
```

The inverter later reported AC-only charging at approximately `49.9 V`,
`60.0 A`, and `2994 W`. Version 0.6.1 then successfully limited utility
charging to `20.0 A`; the Venus page showed `49.60 V`, `20.0 A` DC and an
estimated `4.9 A` AC input current with error code zero.

## Publication policy

- `/Dc/0/Voltage` is QPIGS battery voltage.
- `/Dc/0/Current` is QPIGS charging current only during AC-only charging.
- `/Dc/0/Power` is calculated once as voltage multiplied by that current.
- PV power remains diagnostic and is never added to charger power.
- Mixed AC+SCC charging invalidates standard DC current and power because the
  source split is unavailable.
- `/State` is `3` during AC charging and `0` otherwise; no unsupported charge
  stage is inferred.
- `/ErrorCode` is zero for a valid sample.
- AC input current/power are explicitly estimated from DC charging power,
  configured efficiency and self-consumption.
- AC output voltage, frequency, power, apparent power and load are published on
  the same charger service; no grid or genset service is created.

Default estimation values:

```ini
[power_estimation]
self_consumption_watts = 70
ac_to_dc_efficiency_percent = 95
```

## Controls

Both control families are disabled by default.

Current limits are discovered from `QPIRI`, `QMCHGCR`, and `QMUCHGCR`. A write
must match a live choice, receive `(ACK`, and match the next QPIRI read-back.
The confirmed device advertised total choices `10,20,...,100 A` and utility
choices `2,10,20,...,100 A`.

Version 0.6.0 sent the standard utility command (`MUCHGC050`) to the tested
King II and received `(NAK`. Version 0.7.0 supports both observed PI30 forms.
Auto mode first tries `MUCHGCnnn`, then tries `MUCHGCmnnn` only after a valid
NAK and caches the accepted form. The live King II accepted `MUCHGC0020` and
charged at 20 A. Integer strings from the Venus `dbus` CLI are accepted;
fractional and non-numeric values fail.

`/Ac/In/CurrentLimit` remains AC amperes as required by the Victron charger
model. Its writer calculates a safe DC budget and rounds down to the highest
live utility-current choice. Exact DC control is available through
`/Settings/UtilityChargeCurrentLimit` and `/Settings/ChargeCurrentLimit`.

Mode control is live-confirmed: Mode 4 selected charger-source priority 3
(solar only), and Mode 1 restored priority 2. Both changes received ACK and
matching QPIRI read-back.

`enabled_charger_source_priority` is not a normal fixed priority. It is used
only after a restart that begins in solar-only priority 3, when the driver has
no previously observed enabled value to restore. Values are `0=utility first`,
`1=solar first`, and `2=solar+utility`; empty means reject the ambiguous On.

## Installation lifecycle

The installer preserves `config.ini`, creates a timestamped backup, and leaves
the service inactive. It refuses to overwrite an active service link. The
required update sequence is therefore:

```sh
/data/apps/dbus-voltronic-charger/deactivate.sh
cd /data/dbus-voltronic-charger-0.7.0
./install.sh
cd /data/apps/dbus-voltronic-charger
./activate.sh --confirm-pi30
```

Activation requires explicit `PI30` confirmation, a valid classic 21-field
QPIGS sample, a configured device instance, and the Venus Python/D-Bus runtime.
QMN/model identity is optional metadata.

## Verification status

- 65 unit tests pass.
- `compileall` passes.
- POSIX syntax checks pass for installation, activation, serial lifecycle and
  service scripts.
- The packaged archive was extracted and its complete test suite passed.
- The archive contains no `__pycache__` or `.pyc` files.

## Remaining live validation

- Compare reported values during PV-only charging.
- Confirm mixed AC+PV samples invalidate charger DC current/power as designed.
- Compare estimated AC input power against an external AC meter under several
  DC charge currents and tune the 70 W / 95% defaults if necessary.
- Confirm total-current control through `/Settings/ChargeCurrentLimit`; utility
  DC current and Mode control are already confirmed.

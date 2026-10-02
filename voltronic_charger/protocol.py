"""Wire framing for the read-only Voltronic Q-command protocol."""

from __future__ import annotations

from typing import FrozenSet


class ProtocolError(ValueError):
    """A command or response violates the supported wire protocol."""


# Inquiry commands only. Setting/control commands are deliberately absent.
READ_ONLY_COMMANDS: FrozenSet[str] = frozenset(
    {
        "QPI",
        "QID",
        "QSID",
        "QVFW",
        "QVFW2",
        "QPIRI",
        "QFLAG",
        "QPIGS",
        "QMOD",
        "QPIWS",
        "QDI",
        "QMCHGCR",
        "QMUCHGCR",
        "QOPM",
        "QMN",
        "QGMN",
        "QBEQI",
    }
)

_RESERVED_CRC_BYTES = frozenset((0x0A, 0x0D, 0x28))


def crc16_xmodem(data: bytes) -> int:
    """Return CRC-16/XMODEM (polynomial 0x1021, initial value 0)."""

    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def crc_bytes(data: bytes) -> bytes:
    """Return Voltronic's two wire CRC bytes.

    Q-command implementations escape a CRC byte that would collide with LF,
    CR, or the response start marker by incrementing it. Known command vectors
    are covered by tests so framing changes fail closed.
    """

    value = crc16_xmodem(data)
    high, low = value >> 8, value & 0xFF
    if high in _RESERVED_CRC_BYTES:
        high = (high + 1) & 0xFF
    if low in _RESERVED_CRC_BYTES:
        low = (low + 1) & 0xFF
    return bytes((high, low))


def encode_query(command: str) -> bytes:
    """Encode one explicitly allowlisted read-only inquiry."""

    if command not in READ_ONLY_COMMANDS:
        raise ProtocolError("command is not an allowlisted inquiry: {!r}".format(command))
    try:
        payload = command.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtocolError("command must be ASCII") from exc
    return payload + crc_bytes(payload) + b"\r"


def decode_response(frame: bytes) -> str:
    """Validate and decode one complete response frame, returning its payload."""

    if not isinstance(frame, bytes):
        raise ProtocolError("response frame must be bytes")
    if len(frame) < 4 or not frame.endswith(b"\r"):
        raise ProtocolError("response is incomplete or missing carriage return")
    payload, received_crc = frame[:-3], frame[-3:-1]
    if not payload.startswith(b"("):
        raise ProtocolError("response payload does not start with '('")
    expected_crc = crc_bytes(payload)
    if received_crc != expected_crc:
        raise ProtocolError(
            "response CRC mismatch: received {}, expected {}".format(
                received_crc.hex(), expected_crc.hex()
            )
        )
    try:
        return payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("response payload is not ASCII") from exc


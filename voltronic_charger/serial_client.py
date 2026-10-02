"""Small serial transport that can send inquiry commands only."""

from __future__ import annotations

from typing import Optional

from .protocol import ProtocolError, decode_response, encode_query


class SerialQueryClient:
    def __init__(
        self,
        port: str,
        baudrate: int = 2400,
        timeout: float = 2.0,
        serial_instance=None,
    ) -> None:
        if not port:
            raise ValueError("serial port must be explicit")
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = serial_instance

    def _open(self):
        if self._serial is None:
            try:
                import serial
            except ImportError as exc:
                raise RuntimeError("pyserial is required for live serial access") from exc
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
        return self._serial

    def query_raw(self, command: str) -> bytes:
        connection = self._open()
        frame = encode_query(command)  # allowlist check happens before any write
        if hasattr(connection, "reset_input_buffer"):
            connection.reset_input_buffer()
        connection.write(frame)
        if hasattr(connection, "flush"):
            connection.flush()
        response = connection.read_until(b"\r")
        if not response:
            raise ProtocolError("serial timeout waiting for {} response".format(command))
        return response

    def query(self, command: str) -> str:
        return decode_response(self.query_raw(command))

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


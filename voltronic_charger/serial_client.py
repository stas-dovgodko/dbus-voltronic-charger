"""Small serial transport with allowlisted queries and current-limit writes."""

from __future__ import annotations

import time

from .protocol import (
    ProtocolError,
    decode_response,
    encode_charger_source_priority,
    encode_charge_current_setting,
    encode_query,
)


class SerialQueryClient:
    def __init__(
        self,
        port: str,
        baudrate: int = 2400,
        timeout: float = 2.0,
        command_delay: float = 0.0,
        serial_instance=None,
    ) -> None:
        if not port:
            raise ValueError("serial port must be explicit")
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if command_delay < 0:
            raise ValueError("command_delay cannot be negative")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.command_delay = command_delay
        self._serial = serial_instance
        self._last_write_at = None
        self._detected_utility_current_format = None

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

    def _exchange(self, frame: bytes, description: str) -> bytes:
        connection = self._open()
        now = time.monotonic()
        if self._last_write_at is not None:
            remaining = self.command_delay - (now - self._last_write_at)
            if remaining > 0:
                time.sleep(remaining)
                now += remaining
        if hasattr(connection, "reset_input_buffer"):
            connection.reset_input_buffer()
        connection.write(frame)
        self._last_write_at = now
        if hasattr(connection, "flush"):
            connection.flush()
        response = connection.read_until(b"\r")
        if not response:
            raise ProtocolError(
                "serial timeout waiting for {} response".format(description)
            )
        return response

    def query_raw(self, command: str) -> bytes:
        frame = encode_query(command)  # allowlist check happens before any write
        return self._exchange(frame, command)

    def query(self, command: str) -> str:
        return decode_response(self.query_raw(command))

    def set_charge_current_limit(
        self,
        scope: str,
        current: int,
        parallel_unit: int = 0,
        utility_current_format: str = "auto",
    ) -> None:
        if utility_current_format not in {"auto", "standard", "parallel"}:
            raise ProtocolError(
                "utility current format must be auto, standard, or parallel"
            )

        formats = ("standard",)
        if scope == "utility":
            if utility_current_format == "auto":
                if self._detected_utility_current_format is not None:
                    formats = (self._detected_utility_current_format,)
                else:
                    formats = ("standard", "parallel")
            else:
                formats = (utility_current_format,)

        responses = []
        for selected_format in formats:
            frame = encode_charge_current_setting(
                scope,
                current,
                parallel_unit,
                utility_current_format=selected_format,
            )
            payload = decode_response(
                self._exchange(frame, "{} charge-current setting".format(scope))
            )
            responses.append("{}={}".format(selected_format, payload))
            if payload == "(ACK":
                if scope == "utility":
                    self._detected_utility_current_format = selected_format
                return
            if payload != "(NAK":
                break

        raise ProtocolError(
            "inverter rejected {} charge-current setting: {}".format(
                scope, ", ".join(responses)
            )
        )

    def set_charger_source_priority(self, priority: int) -> None:
        frame = encode_charger_source_priority(priority)
        payload = decode_response(
            self._exchange(frame, "charger-source priority setting")
        )
        if payload != "(ACK":
            raise ProtocolError(
                "inverter rejected charger-source priority setting: {}".format(
                    payload
                )
            )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

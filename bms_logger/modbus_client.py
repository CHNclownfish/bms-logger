from __future__ import annotations

from pymodbus.client import ModbusTcpClient

from .models import DeviceConfig, RegisterDef


DEFAULT_REGISTERS = {
    "voltage": RegisterDef(name="System voltage", address=0x0020, scale=0.1, value_offset=0.0),
    "current": RegisterDef(name="System current", address=0x0021, scale=1.0, value_offset=-20000.0),
    "soc": RegisterDef(name="SOC", address=0x0022, scale=0.1, value_offset=0.0),
}


class BmsModbusReader:
    def __init__(self, config: DeviceConfig):
        self.config = config
        self.client = ModbusTcpClient(host=config.host, port=config.port, timeout=2)

    def connect(self) -> bool:
        return bool(self.client.connect())

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def read_system_data(self) -> dict[str, float]:
        """Batch read 0x0020~0x0022 in a single Modbus request."""
        response = self.client.read_holding_registers(
            address=DEFAULT_REGISTERS["voltage"].address,
            count=3,
            device_id=self.config.unit_id,
        )
        if response.isError():
            raise RuntimeError(
                f"Read failed: addr=0x{DEFAULT_REGISTERS['voltage'].address:04X}~0x0022, error={response}"
            )

        if not hasattr(response, "registers") or len(response.registers) < 3:
            raise RuntimeError("Invalid register response length")

        regs = [int(value) for value in response.registers[:3]]
        return {
            "voltage": DEFAULT_REGISTERS["voltage"].decode(regs[0]),
            "current": DEFAULT_REGISTERS["current"].decode(regs[1]),
            "soc": DEFAULT_REGISTERS["soc"].decode(regs[2]),
        }

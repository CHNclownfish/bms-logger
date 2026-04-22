from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from .modbus_client import BmsModbusReader
from .models import DeviceConfig, SampleRecord


class DevicePollingThread(threading.Thread):
    def __init__(self, device: DeviceConfig, manager: "PollingManager"):
        super().__init__(daemon=True, name=f"poll-{device.name}")
        self.device = device
        self.manager = manager
        self.stop_event = threading.Event()
        self.reader = BmsModbusReader(device)

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                started_at = time.monotonic()
                timestamp = datetime.now()
                self._poll_once(timestamp)

                elapsed = time.monotonic() - started_at
                sleep_seconds = max(0.0, self.device.poll_interval - elapsed)
                if self.stop_event.wait(sleep_seconds):
                    break
        finally:
            self.reader.close()

    def _poll_once(self, timestamp: datetime) -> None:
        try:
            if not self.reader.client.connected:
                self.manager.device_state.emit(self.device.name, "connecting")
                if not self.reader.connect():
                    raise ConnectionError("Unable to connect")

            values = self.reader.read_system_data()
            record = SampleRecord(
                timestamp=timestamp,
                device_name=self.device.name,
                host=self.device.host,
                port=self.device.port,
                unit_id=self.device.unit_id,
                soc_pct=round(values["soc"], 3),
                voltage_v=round(values["voltage"], 3),
                current_a=round(values["current"], 3),
                status="ok",
                error="",
            )
            self.manager.device_state.emit(self.device.name, "online")
            self.manager.sample_received.emit(record)
        except Exception as exc:
            record = SampleRecord(
                timestamp=timestamp,
                device_name=self.device.name,
                host=self.device.host,
                port=self.device.port,
                unit_id=self.device.unit_id,
                soc_pct=None,
                voltage_v=None,
                current_a=None,
                status="error",
                error=str(exc),
            )
            self.manager.device_state.emit(self.device.name, "error")
            self.manager.sample_received.emit(record)
            self.reader.close()


class PollingManager(QObject):
    sample_received = Signal(object)
    device_state = Signal(str, str)
    finished = Signal()

    def __init__(self, devices: list[DeviceConfig]):
        super().__init__()
        self.devices = [dev for dev in devices if dev.enabled]
        self._threads: list[DevicePollingThread] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._threads = [DevicePollingThread(device=dev, manager=self) for dev in self.devices]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        for thread in self._threads:
            thread.stop()
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads.clear()
        self._started = False
        self.finished.emit()

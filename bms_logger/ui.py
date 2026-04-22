from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .exporter import export_samples_to_device_files
from .models import DeviceConfig, SampleRecord
from .worker import PollingManager


class DeviceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, existing: DeviceConfig | None = None):
        super().__init__(parent)
        self.setWindowTitle("设备配置")

        self.name_edit = QLineEdit(existing.name if existing else "BMS-1")
        self.host_edit = QLineEdit(existing.host if existing else "192.168.1.100")

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(existing.port if existing else 502)

        self.unit_spin = QSpinBox()
        self.unit_spin.setRange(1, 255)
        self.unit_spin.setValue(existing.unit_id if existing else 1)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setDecimals(1)
        self.interval_spin.setRange(0.2, 3600.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(existing.poll_interval if existing else 1.0)

        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setChecked(existing.enabled if existing else True)

        form = QFormLayout()
        form.addRow("设备名称", self.name_edit)
        form.addRow("IP 地址", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("Unit ID", self.unit_spin)
        form.addRow("采样周期(秒)", self.interval_spin)
        form.addRow("", self.enabled_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def get_config(self) -> DeviceConfig:
        return DeviceConfig(
            name=self.name_edit.text().strip() or "BMS",
            host=self.host_edit.text().strip() or "127.0.0.1",
            port=self.port_spin.value(),
            unit_id=self.unit_spin.value(),
            poll_interval=self.interval_spin.value(),
            enabled=self.enabled_check.isChecked(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMS Logger")
        self.resize(1100, 700)

        self.devices: list[DeviceConfig] = []
        self.records: list[SampleRecord] = []
        self.polling_manager: PollingManager | None = None

        self.device_table = self._create_device_table()
        self.data_table = self._create_data_table()
        self.status_label = QLabel("就绪")

        controls = self._build_controls()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(controls)
        layout.addWidget(self._wrap_group("设备列表", self.device_table), 2)
        layout.addWidget(self._wrap_group("实时数据（最近样本）", self.data_table), 3)
        layout.addWidget(self.status_label)
        self.setCentralWidget(central)

    def _wrap_group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        lay = QVBoxLayout(group)
        lay.addWidget(widget)
        return group

    def _build_controls(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)

        add_btn = QPushButton("添加设备")
        edit_btn = QPushButton("编辑设备")
        del_btn = QPushButton("删除设备")
        start_btn = QPushButton("开始采集")
        stop_btn = QPushButton("停止采集")
        export_btn = QPushButton("按设备导出 Excel")
        save_btn = QPushButton("保存配置")
        load_btn = QPushButton("加载配置")

        add_btn.clicked.connect(self.add_device)
        edit_btn.clicked.connect(self.edit_device)
        del_btn.clicked.connect(self.delete_device)
        start_btn.clicked.connect(self.start_polling)
        stop_btn.clicked.connect(self.stop_polling)
        export_btn.clicked.connect(self.export_excel)
        save_btn.clicked.connect(self.save_config)
        load_btn.clicked.connect(self.load_config)

        buttons = [add_btn, edit_btn, del_btn, start_btn, stop_btn, export_btn, save_btn, load_btn]
        for idx, btn in enumerate(buttons):
            layout.addWidget(btn, 0, idx)

        help_text = QLabel(
            "默认单次批量读取寄存器：0x0020~0x0022（System voltage / System current / SOC）；每个设备独立线程按自己的采样周期运行。"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text, 1, 0, 1, len(buttons))
        return widget

    def _create_device_table(self) -> QTableWidget:
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["名称", "IP", "端口", "Unit ID", "周期(s)", "启用"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        return table

    def _create_data_table(self) -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels([
            "时间",
            "设备",
            "SOC(%)",
            "电压(V)",
            "电流(A)",
            "状态",
            "错误",
            "连接",
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        return table

    def refresh_device_table(self) -> None:
        self.device_table.setRowCount(len(self.devices))
        for row, dev in enumerate(self.devices):
            values = [dev.name, dev.host, str(dev.port), str(dev.unit_id), str(dev.poll_interval), "是" if dev.enabled else "否"]
            for col, value in enumerate(values):
                self.device_table.setItem(row, col, QTableWidgetItem(value))

    def upsert_latest_record(self, record: SampleRecord) -> None:
        target_row = None
        for row in range(self.data_table.rowCount()):
            item = self.data_table.item(row, 1)
            if item and item.text() == record.device_name:
                target_row = row
                break
        if target_row is None:
            target_row = self.data_table.rowCount()
            self.data_table.insertRow(target_row)

        values = [
            record.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            record.device_name,
            "" if record.soc_pct is None else str(record.soc_pct),
            "" if record.voltage_v is None else str(record.voltage_v),
            "" if record.current_a is None else str(record.current_a),
            record.status,
            record.error,
            f"{record.host}:{record.port} / {record.unit_id}",
        ]
        for col, value in enumerate(values):
            self.data_table.setItem(target_row, col, QTableWidgetItem(value))

    def add_device(self) -> None:
        dialog = DeviceDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.devices.append(dialog.get_config())
            self.refresh_device_table()

    def _selected_device_index(self) -> int | None:
        row = self.device_table.currentRow()
        return row if row >= 0 else None

    def edit_device(self) -> None:
        idx = self._selected_device_index()
        if idx is None:
            QMessageBox.information(self, "提示", "请先选择一个设备。")
            return
        dialog = DeviceDialog(self, self.devices[idx])
        if dialog.exec() == QDialog.Accepted:
            self.devices[idx] = dialog.get_config()
            self.refresh_device_table()

    def delete_device(self) -> None:
        idx = self._selected_device_index()
        if idx is None:
            QMessageBox.information(self, "提示", "请先选择一个设备。")
            return
        del self.devices[idx]
        self.refresh_device_table()

    def start_polling(self) -> None:
        if self.polling_manager is not None:
            QMessageBox.information(self, "提示", "采集已经在运行。")
            return
        enabled_devices = [dev for dev in self.devices if dev.enabled]
        if not enabled_devices:
            QMessageBox.warning(self, "提示", "请至少配置一个启用的设备。")
            return

        self.records.clear()
        self.data_table.setRowCount(0)

        self.polling_manager = PollingManager(self.devices)
        self.polling_manager.sample_received.connect(self.on_sample_received)
        self.polling_manager.device_state.connect(self.on_device_state_changed)
        self.polling_manager.finished.connect(self.on_worker_finished)
        self.polling_manager.start()
        self.status_label.setText(f"采集中... 设备数: {len(enabled_devices)}")

    def stop_polling(self) -> None:
        if self.polling_manager is not None:
            manager = self.polling_manager
            self.polling_manager = None
            self.status_label.setText("正在停止...")
            manager.stop()

    def on_worker_finished(self) -> None:
        self.status_label.setText("已停止")

    def on_sample_received(self, record: SampleRecord) -> None:
        self.records.append(record)
        self.upsert_latest_record(record)
        self.status_label.setText(f"已采样 {len(self.records)} 条")

    def on_device_state_changed(self, device_name: str, state: str) -> None:
        self.statusBar().showMessage(f"{device_name}: {state}")

    def export_excel(self) -> None:
        if not self.records:
            QMessageBox.information(self, "提示", "当前没有采样数据。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not directory:
            return
        paths = export_samples_to_device_files(self.records, directory)
        if not paths:
            QMessageBox.warning(self, "提示", "没有可导出的设备数据。")
            return
        joined = "\n".join(str(path) for path in paths)
        QMessageBox.information(self, "完成", f"已按设备导出 {len(paths)} 个文件：\n{joined}")

    def save_config(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "保存配置", "devices.json", "JSON Files (*.json)")
        if not file_path:
            return
        data = [asdict(dev) for dev in self.devices]
        Path(file_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "完成", "配置已保存。")

    def load_config(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON Files (*.json)")
        if not file_path:
            return
        raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
        self.devices = [DeviceConfig.from_dict(item) for item in raw]
        self.refresh_device_table()
        QMessageBox.information(self, "完成", "配置已加载。")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.stop_polling()
        super().closeEvent(event)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

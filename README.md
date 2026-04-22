# BMS Logger

基于 Python + PySide6 的 BMS 采样工具：
- Modbus TCP 多设备连接
- 每个设备独立线程采样
- 单次批量读取 `0x0020~0x0022`
- 默认采集 `System voltage / System current / SOC`
- 按设备分别导出 Excel
- GitHub Actions 打包 Windows EXE

## 默认寄存器
根据你提供的点表：
- `System voltage` = `0x0020`
- `System current` = `0x0021`，偏移 `-20000`
- `SOC` = `0x0022`

这三个寄存器是连续地址，所以程序采用 **一次 Modbus 批量读取 3 个寄存器** 的方式，保证同一时刻采样。

## 运行
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## 采样说明
- 每台设备一个独立线程
- 如果设备 A/B/C 都设置为 `1.0s`
- 则每台设备都会以各自的 1 秒周期运行
- 一个设备超时或断连，不会拖慢其他设备

## 导出
点击“按设备导出 Excel”后，会在所选目录下生成类似文件：
- `BMS-1_20260422_101500_20260422_103000.xlsx`
- `BMS-2_20260422_101500_20260422_103000.xlsx`

## 打包 EXE
### 本地打包
```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name BMSLogger app.py
```

### GitHub Actions
推送到 GitHub 后，Actions 会自动生成 Windows 可执行文件压缩包。

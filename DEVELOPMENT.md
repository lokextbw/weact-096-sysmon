# WeAct Studio 0.96" USB 系统监视器 — 开发文档

## 一、硬件规格

| 项目 | 参数 |
|------|------|
| 型号 | WeAct Studio 0.96" USB System Monitor |
| 屏幕 | 0.96 英寸彩色 IPS/OLED，80×160 像素 |
| 接口 | USB-A 直插，免额外供电 |
| 主控 | USB 转串口芯片 CH340/CH341 |
| VID/PID | `1A86` / `FE0C` |
| 固件版本 | V1.0.0.2（已测试） |
| 串口参数 | 115200 baud, 8N1 |
| 最大波特率 | 115200 |

## 二、通信协议

协议来源：WeAct Studio SystemMonitor，与 turing-smart-screen-python 项目兼容。

### 2.1 命令帧格式

所有命令以单字节命令码开头，以 `CMD_END` (`0x0A`) 结尾：

```
[CMD] [参数...] [0x0A]
```

### 2.2 命令列表

| 命令 | 代码 | 格式 | 说明 |
|------|------|------|------|
| `CMD_WHO_AM_I` | `0x81` | `81 0A` | 握手/识别（发送后读回复） |
| `CMD_SYSTEM_VERSION` | `0x42` | `42 80 0A` | 查询固件版本，返回 19 字节 |
| `CMD_SET_ORIENTATION` | `0x02` | `02 [方向:1B] 0A` | 屏幕方向 (0=竖屏) |
| `CMD_SET_BRIGHTNESS` | `0x03` | `03 [0-255:1B] [ms:2B LE] 0A` | 亮度（0-255 映射自 0-100%） |
| `CMD_FULL` | `0x04` | `04 00 00 00 00 [wL] [wH] [hL] [hH] [RGB565:2B LE] 0A` | 纯色填充全屏 |
| `CMD_SET_BITMAP` | `0x05` | `05 [x0L] [x0H] [y0L] [y0H] [x1L] [x1H] [y1L] [y1H] 0A` + 像素数据 | 发送位图区域 |
| `CMD_FREE` | `0x07` | `07 0A` | 释放/息屏 |

### 2.3 CMD_SET_BITMAP 详解（核心命令）

**命令头（10 字节）：**
```
05            — CMD_SET_BITMAP
x0 & 0xFF     — 起始列 低字节
x0 >> 8       — 起始列 高字节
y0 & 0xFF     — 起始行 低字节
y0 >> 8       — 起始行 高字节
x1 & 0xFF     — 结束列 低字节
x1 >> 8       — 结束列 高字节
y1 & 0xFF     — 结束行 低字节
y1 >> 8       — 结束行 高字节
0A            — CMD_END
```

**像素数据：**
- 格式：RGB565 小端序（Little-Endian）
- 每个像素 2 字节：`struct.pack("<H", rgb565_value)`
- RGB565 编码：`((R>>3)<<11) | ((G>>2)<<5) | (B>>3)`
- 数据量：`(x1-x0+1) × (y1-y0+1) × 2` 字节
- 建议分块发送，每块大小 `宽度 × 8 × 2` 字节

**全屏 80×160 示例：**
```python
cmd = bytearray([0x05, 0x00,0x00, 0x00,0x00, 0x4F,0x00, 0x9F,0x00, 0x0A])
ser.write(cmd)
# 80×160×2 = 25600 字节 RGB565 LE 数据
ser.write(pixel_data)
```

### 2.4 初始化流程

```python
# 1. 打开串口
ser = serial.Serial("COM4", 115200, timeout=0.5)

# 2. 清空缓冲区
ser.read_all()

# 3. 查询版本（可选）
ser.write(bytearray([0x42 | 0x80, 0x0A]))  # CMD_SYSTEM_VERSION | CMD_READ
time.sleep(0.3)
resp = ser.read(19)  # 固件版本在 resp[1:9]

# 4. 设置亮度
ser.write(bytearray([0x03, brightness, 0xE8, 0x03, 0x0A]))

# 5. 发送图像（见 2.3）

# 6. 退出时关闭串口即可，图像保持显示
ser.close()
```

### 2.5 注意事项

- **不要发送 `CMD_FREE` (`07 0A`)**：会导致屏幕熄灭
- 关闭串口不会清除画面，最后一帧会持续显示
- 同一时间只能有一个进程占用串口
- 设备不主动发送数据，仅在收到查询命令时响应

## 三、软件架构

`usb_monitor.py` 的模块结构：

```
usb_monitor.py
├── 协议常量定义        CMD_*, BAUD_RATE, DISPLAY_W/H
├── 串口自动检测        find_display_port()
├── 显示协议层          init_display(), set_brightness(), send_bitmap()
├── 系统信息采集        get_cpu_percent(), get_memory(), get_disk_usage(),
│                      get_temperatures(), get_network_speed(), get_host_ip()
├── 字体加载            get_font(size)  — 优先 SimHei/微软雅黑
├── 屏幕渲染            render_screen()  — 80×160 布局
└── 主循环              main()  — 采集→渲染→发送→等待
```

### 3.1 渲染函数接口

```python
def render_screen(cpu_pct, mem_pct, ip, up_str, down_str) -> PIL.Image:
    """
    参数:
        cpu_pct:  float   CPU 使用率 0-100
        mem_pct:  float   内存使用率 0-100
        ip:       str     IP 地址字符串
        up_str:   str     上传速度（如 "128K/s"）
        down_str: str     下载速度（如 "2.4M/s"）
    返回:
        PIL.Image  80×160 RGB 图像
    """
```

### 3.2 添加新指标的方法

**示例：添加磁盘使用率**

1. 添加采集函数：
```python
def get_disk_usage() -> float:
    return psutil.disk_usage("/").percent
```

2. 修改 `render_screen()` 签名和布局：
```python
def render_screen(cpu_pct, mem_pct, disk_pct, ip, up_str, down_str):
    # 在合适位置添加 DSK 行
    ...
```

3. 在主循环中采集并传入：
```python
disk_pct = get_disk_usage()
img = render_screen(cpu_pct, mem_pct, disk_pct, ip, up_str, down_str)
```

## 四、命令行参数

```
usage: usb_monitor.py [-h] [-p PORT] [-b BRIGHTNESS] [-i INTERVAL] [-l] [-v]

选项:
  -p, --port       串口路径（Windows: COM4, Linux: /dev/ttyACM0）
                   不指定则自动检测（通过 VID/PID 匹配）
  -b, --brightness 亮度 0-100（默认 80）
  -i, --interval   刷新间隔秒数（默认 1.0）
  -l, --list       列出所有可用串口
  -v, --verbose    详细日志
```

### 使用示例

```bash
# Windows 自动检测
python usb_monitor.py

# Linux 手动指定
python3 usb_monitor.py -p /dev/ttyACM0 -b 60 -i 2.0

# 后台运行（Windows）
Start-Process python -ArgumentList "usb_monitor.py","-b","60" -WindowStyle Hidden

# 后台运行（Linux）
nohup python3 usb_monitor.py -b 60 &
```

## 五、布局设计参考

当前 80×160 布局（字号 12px 统一）：

```
Y=4     ┌──────────────────────────┐
        │        SysMon           │  ← 标题 14px
Y=22    │──────────────────────────│  ← 分隔线
Y=30    │ CPU              73%     │  ← 12px
Y=46    │ ████████████████░░░░░░   │  ← 进度条 4px
Y=58    │ MEM              62%     │
Y=74    │ ██████████████░░░░░░░░   │
Y=90    │──────────────────────────│
Y=98    │ ↓ 2.4M/s                 │  ← 下载
Y=114   │ ↑ 128K/s                 │  ← 上传
Y=134   │ 192.168.1.100            │  ← IP 10px
        └──────────────────────────┘
```

颜色规则：
- 白色：使用率 < 70%
- 橙色 `(255,200,50)`：70% ≤ 使用率 < 90%
- 红色 `(255,50,50)`：使用率 ≥ 90%

## 六、跨平台注意事项

### Windows
- 串口路径：`COMx`
- 字体：`C:\Windows\Fonts\simhei.ttf`（黑体，支持中文）
- 温度：通过 WMI 或第三方工具获取

### Linux
- 串口路径：`/dev/ttyACMx` 或 `/dev/ttyUSBx`
- 权限：需 `dialout` 组或 `sudo`
- 字体：`/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf`
- 温度：`/sys/class/thermal/thermal_zone*/temp`

## 七、依赖

```
pyserial>=3.5     # 串口通信
psutil>=5.9       # 系统信息采集
Pillow>=9.0       # 图像渲染（含 ImageFont 中文支持）
```

安装：
```bash
pip install pyserial psutil Pillow
```

## 八、调试技巧

1. **列出可用串口**：`python usb_monitor.py -l`
2. **详细日志**：`python usb_monitor.py -v`
3. **预览渲染效果**：修改脚本调用 `render_screen()` 后 `img.save("preview.png")`
4. **残留进程**：`Get-Process python | Stop-Process`（Windows）或 `pkill python`（Linux）
5. **串口占用检测**：运行前确认无其他程序占用目标串口

## 九、相关项目

- [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) — 核心协议参考
- [netid-monitor](https://github.com/vikavorkin/netid-monitor) — 简化版 Python 守护进程

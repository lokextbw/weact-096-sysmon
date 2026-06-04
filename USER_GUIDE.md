# WeAct 0.96" USB 系统监视屏 — 运行指南

## 环境准备

### 安装 Python 依赖

**Windows (PowerShell):**
```powershell
pip install pyserial psutil Pillow
```

**Linux:**
```bash
pip3 install pyserial psutil Pillow
```

> 依赖：`pyserial`（串口）`psutil`（系统信息）`Pillow`（图像渲染）

---

## Windows

### 确认设备

```powershell
python usb_monitor.py -l
```

输出示例：
```
Available serial ports:
  COM4: USB 串行设备 (COM4) [VID:6790, PID:5740, SN:N/A]
```

> 预期 VID/PID：`1A86:FE0C`（WeAct CH340 芯片）

### 前台运行

```powershell
# 自动检测端口，默认亮度 80%，1 秒刷新
python usb_monitor.py

# 自定义亮度 60%，2 秒刷新
python usb_monitor.py -b 60 -i 2.0

# 手动指定端口
python usb_monitor.py -p COM4
```

`Ctrl+C` 停止。

### 后台运行

```powershell
# 静默启动
Start-Process python -ArgumentList "usb_monitor.py","-b","60" -WindowStyle Hidden

# 查看是否在运行
Get-Process python
```

### 停止

```powershell
Get-Process python | Stop-Process
```

---

## Linux

### 确认设备

```bash
python3 usb_monitor.py -l

# 或直接查看系统设备
ls /dev/ttyACM* /dev/ttyUSB*
```

### 串口权限（一次性设置）

```bash
# 将当前用户加入 dialout 组
sudo usermod -aG dialout $USER

# 注销重新登录后生效
# 临时方案：直接用 sudo 运行
```

### 前台运行

```bash
# 自动检测
python3 usb_monitor.py

# 手动指定（常见路径 /dev/ttyACM0 或 /dev/ttyUSB0）
python3 usb_monitor.py -p /dev/ttyACM0 -b 60 -i 2.0
```

`Ctrl+C` 停止。

### 后台运行

```bash
# 后台启动，日志输出到文件
nohup python3 usb_monitor.py -b 60 > /dev/null 2>&1 &

# 查看进程
ps aux | grep usb_monitor
```

### 停止

```bash
pkill -f usb_monitor.py
```

### 开机自启（systemd）

创建服务文件 `/etc/systemd/system/usb-monitor.service`：

```ini
[Unit]
Description=WeAct USB System Monitor
After=multi-user.target

[Service]
Type=simple
User=你的用户名
ExecStart=/usr/bin/python3 /home/你的用户名/usb_monitor.py -b 60 -i 2.0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

启用：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now usb-monitor
sudo systemctl status usb-monitor   # 查看状态
```

---

## 参数速查

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `-p` | 串口路径 | 自动检测 | `-p COM4` 或 `-p /dev/ttyACM0` |
| `-b` | 亮度 0–100 | 80 | `-b 50` |
| `-i` | 刷新间隔(秒) | 1.0 | `-i 2.0` |
| `-l` | 列出可用串口 | — | `-l` |
| `-v` | 调试日志 | — | `-v` |

---

## 常见问题

**Q: 运行报 "could not open port"**
→ 检查是否有其他程序（串口助手、IDE、旧进程）占用该串口。杀掉残留进程后重试。

**Q: 屏幕无显示**
→ 确认亮度参数 `-b` 不为 0。默认 80%。

**Q: 中文标题乱码（已改用英文缩写 SysMon）**
→ 脚本自动使用 SimHei（黑体），确认字体文件存在：
  - Windows: `C:\Windows\Fonts\simhei.ttf`
  - Linux: `fc-list :lang=zh` 查看可用中文字体

**Q: Linux 下提示权限不足**
→ 执行 `sudo usermod -aG dialout $USER` 后重新登录。

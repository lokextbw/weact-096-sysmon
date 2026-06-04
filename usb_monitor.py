#!/usr/bin/env python3
"""
WeAct Studio 0.96" USB System Monitor - Cross-platform Python Monitor
Works on Windows & Linux. Displays CPU/Memory/Network/Temperature
on the 80x160 display via USB serial (CDC).

Protocol: WeAct Studio SystemMonitor (verified with V1.0.0.2)
Based on turing-smart-screen-python by mathoudebine.
"""

import sys
import os
import time
import socket
import struct
import logging
import argparse
from typing import Optional, Dict, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

# ==================== Logging ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("usbmon")

# ==================== Display Protocol Constants ====================
# WeAct Studio SystemMonitor protocol (CMD + data + CMD_END)
CMD_SET_ORIENTATION  = 0x02
CMD_SET_BRIGHTNESS   = 0x03
CMD_FULL             = 0x04
CMD_SET_BITMAP       = 0x05
CMD_WHO_AM_I         = 0x81
CMD_SYSTEM_VERSION   = 0x42
CMD_READ             = 0x80
CMD_FREE             = 0x07
CMD_END              = 0x0A

# Auto-detection: VID/PID for WeAct CH340
KNOWN_VID_PID = [
    (0x1A86, 0xFE0C),  # CH340/CH341 (WeAct common)
    (0x0483, 0x5740),  # STM32 Virtual COM Port
]
KNOWN_SERIAL_PREFIX = ["AB"]  # WeAct serial number prefix

BAUD_RATE    = 115200
DISPLAY_W    = 80
DISPLAY_H    = 160

# ==================== Color Palette ====================
BG_COLOR      = (10, 12, 22)
BG_ALT        = (18, 22, 35)
ACCENT        = (0, 210, 255)
ACCENT2       = (0, 255, 140)
WHITE         = (230, 235, 245)
LABEL_COLOR   = (100, 140, 180)
WARNING       = (255, 180, 50)
DANGER        = (255, 75, 75)
NET_COLOR     = (180, 130, 255)
TEMP_COLOR    = (255, 160, 100)

# ==================== Port Detection ====================
def find_display_port(preferred: Optional[str] = None) -> Optional[str]:
    """Auto-detect WeAct display serial port."""
    if preferred:
        return preferred

    for p in serial.tools.list_ports.comports():
        # Match by VID/PID
        if p.vid and p.pid and (p.vid, p.pid) in KNOWN_VID_PID:
            log.info(f"Found by VID/PID: {p.device} ({p.description})")
            return p.device
        # Match by serial number prefix
        if isinstance(p.serial_number, str):
            for prefix in KNOWN_SERIAL_PREFIX:
                if p.serial_number.startswith(prefix):
                    log.info(f"Found by serial: {p.device} ({p.description})")
                    return p.device

    # Fallback: first available COM port
    ports = list(serial.tools.list_ports.comports())
    if ports:
        log.warning(f"Fallback to first port: {ports[0].device}")
        return ports[0].device
    return None

# ==================== Display Protocol ====================
def send_command(ser: serial.Serial, data: bytearray):
    """Send a command (data must include CMD_END terminator)."""
    ser.write(data)

def init_display(ser: serial.Serial) -> str:
    """Initialize display and return version string."""
    ser.read_all()
    time.sleep(0.1)

    # Query version: CMD_SYSTEM_VERSION | CMD_READ + CMD_END
    cmd = bytearray([CMD_SYSTEM_VERSION | CMD_READ, CMD_END])
    ser.write(cmd)
    time.sleep(0.3)

    resp = ser.read(32)
    version = "unknown"
    if resp and len(resp) >= 9:
        try:
            version = resp[1:9].decode("ascii", errors="replace").strip("\x00").strip()
        except Exception:
            pass

    ser.reset_input_buffer()
    log.info(f"Display initialized, version: {version}")
    return version

def set_brightness(ser: serial.Serial, level: int = 80):
    """Set brightness 0-100 (mapped to 0-255 internally)."""
    level = max(0, min(100, level))
    converted = int((level / 100) * 255)
    # brightness_ms defaults to 1000
    cmd = bytearray([
        CMD_SET_BRIGHTNESS,
        converted & 0xFF,
        1000 & 0xFF,
        (1000 >> 8) & 0xFF,
        CMD_END
    ])
    send_command(ser, cmd)
    log.debug(f"Brightness: {level}% ({converted}/255)")

def set_orientation(ser: serial.Serial, orientation: int = 0):
    """Set orientation: 0=portrait, 1=landscape, etc."""
    cmd = bytearray([CMD_SET_ORIENTATION, orientation, CMD_END])
    send_command(ser, cmd)

def send_bitmap(ser: serial.Serial, img: Image.Image):
    """Send PIL image as RGB565 LE bitmap to display."""
    w, h = img.size
    if w != DISPLAY_W or h != DISPLAY_H:
        img = img.resize((DISPLAY_W, DISPLAY_H))

    x0, y0 = 0, 0
    x1, y1 = DISPLAY_W - 1, DISPLAY_H - 1

    # CMD_SET_BITMAP header (10 bytes): cmd, x0L, x0H, y0L, y0H, x1L, x1H, y1L, y1H, CMD_END
    cmd = bytearray([
        CMD_SET_BITMAP,
        x0 & 0xFF, (x0 >> 8) & 0xFF,
        y0 & 0xFF, (y0 >> 8) & 0xFF,
        x1 & 0xFF, (x1 >> 8) & 0xFF,
        y1 & 0xFF, (y1 >> 8) & 0xFF,
        CMD_END
    ])
    ser.write(cmd)

    # Convert image to RGB565 little-endian
    pix = img.convert("RGB").load()
    chunk = bytearray()
    CHUNK_SIZE = DISPLAY_W * 8 * 2  # 8 rows per chunk

    for row in range(DISPLAY_H):
        for col in range(DISPLAY_W):
            r, g, b = pix[col, row]
            val = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            chunk += struct.pack("<H", val)  # little-endian
            if len(chunk) >= CHUNK_SIZE:
                ser.write(chunk)
                chunk = bytearray()
    if chunk:
        ser.write(chunk)

def free_display(ser: serial.Serial):
    """Release display (screen off)."""
    cmd = bytearray([CMD_FREE, CMD_END])
    send_command(ser, cmd)

# ==================== System Info ====================
def get_cpu_percent() -> float:
    return psutil.cpu_percent(interval=0.1)

def get_memory() -> Tuple[float, float, float]:
    mem = psutil.virtual_memory()
    return mem.percent, mem.used / (1024**3), mem.total / (1024**3)

def get_disk_usage() -> float:
    """Return root disk usage percent (cross-platform)."""
    try:
        return psutil.disk_usage("/").percent
    except Exception:
        return 0.0

def get_temperatures() -> Dict[str, float]:
    temps = {}
    try:
        if hasattr(psutil, "sensors_temperatures"):
            st = psutil.sensors_temperatures()
            if st:
                for name, entries in st.items():
                    for entry in entries:
                        label = entry.label or name
                        if entry.current > 0:
                            temps[label] = entry.current
    except Exception:
        pass

    # Windows fallback
    if not temps and sys.platform == "win32":
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "path", "Win32_PerfFormattedData_Counters_ThermalZoneInformation",
                 "get", "Temperature"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split("\n")[1:]:
                line = line.strip()
                if line:
                    try:
                        t = float(line) / 10.0 - 273.15
                        temps["CPU"] = t
                    except ValueError:
                        pass
        except Exception:
            pass

    # Linux fallback
    if not temps and sys.platform == "linux":
        for i in range(6):
            tpath = f"/sys/class/thermal/thermal_zone{i}/temp"
            ttype = f"/sys/class/thermal/thermal_zone{i}/type"
            if os.path.exists(tpath):
                try:
                    with open(tpath) as f:
                        val = int(f.read().strip()) / 1000.0
                    label = f"TZ{i}"
                    if os.path.exists(ttype):
                        with open(ttype) as f:
                            label = f.read().strip()
                    temps[label] = val
                except Exception:
                    pass

    return temps

def get_network_speed(prev_net, interval=1.0):
    net = psutil.net_io_counters()
    if prev_net is None:
        return net, 0, 0
    upload = (net.bytes_sent - prev_net.bytes_sent) / interval
    download = (net.bytes_recv - prev_net.bytes_recv) / interval
    return net, upload, download

def format_speed(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f}B/s"
    elif bps < 1024 * 1024:
        return f"{bps/1024:.0f}K/s"
    else:
        return f"{bps/(1024*1024):.1f}M/s"

def get_host_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "N/A"

# ==================== Font Loading ====================
FONT_CACHE: Dict[int, ImageFont.FreeTypeFont] = {}

def get_font(size: int) -> ImageFont.FreeTypeFont:
    if size in FONT_CACHE:
        return FONT_CACHE[size]

    paths = []
    if sys.platform == "win32":
        paths = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\consola.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]

    for fp in paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, size)
                FONT_CACHE[size] = font
                return font
            except Exception:
                continue

    font = ImageFont.load_default()
    FONT_CACHE[size] = font
    return font
# ==================== Screen Rendering ====================
def draw_bar(draw, x, y, w, h, percent, color):
    """Horizontal progress bar."""
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=BG_ALT, outline=ACCENT)
    fill_w = int((w - 2) * percent / 100)
    if fill_w > 0:
        draw.rectangle([x + 1, y + 1, x + fill_w, y + h - 2], fill=color)

def render_screen(cpu_pct, mem_pct, ip, up_str, down_str):
    img = Image.new("RGB", (DISPLAY_W, DISPLAY_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    f_title = get_font(14)
    f_body  = get_font(12)
    f_small = get_font(10)
    W = (255, 255, 255)
    G = (150, 150, 150)
    D = (45, 45, 45)
    title = "SysMon"
    tw = draw.textlength(title, font=f_title) if hasattr(draw, "textlength") else len(title) * 8
    draw.text(((DISPLAY_W - tw) // 2, 4), title, fill=W, font=f_title)
    y = 22
    draw.line([8, y, DISPLAY_W - 9, y], fill=D, width=1)
    y += 8
    c = W if cpu_pct < 70 else ((255, 200, 50) if cpu_pct < 90 else (255, 50, 50))
    draw.text((6, y), "CPU", fill=G, font=f_body)
    t = f"{cpu_pct:.0f}%"
    tw = draw.textlength(t, font=f_body) if hasattr(draw, "textlength") else len(t) * 8
    draw.text((DISPLAY_W - 6 - tw, y), t, fill=c, font=f_body)
    y += 16
    draw.rectangle([6, y, DISPLAY_W - 7, y + 4], fill=(30, 30, 30))
    fw = int((DISPLAY_W - 14) * cpu_pct / 100)
    if fw > 0:
        draw.rectangle([7, y + 1, 7 + fw, y + 3], fill=c)
    y += 12
    c = W if mem_pct < 70 else ((255, 200, 50) if mem_pct < 90 else (255, 50, 50))
    draw.text((6, y), "MEM", fill=G, font=f_body)
    t = f"{mem_pct:.0f}%"
    tw = draw.textlength(t, font=f_body) if hasattr(draw, "textlength") else len(t) * 8
    draw.text((DISPLAY_W - 6 - tw, y), t, fill=c, font=f_body)
    y += 16
    draw.rectangle([6, y, DISPLAY_W - 7, y + 4], fill=(30, 30, 30))
    fw = int((DISPLAY_W - 14) * mem_pct / 100)
    if fw > 0:
        draw.rectangle([7, y + 1, 7 + fw, y + 3], fill=c)
    y += 16
    draw.line([8, y, DISPLAY_W - 9, y], fill=D, width=1)
    y += 8
    draw.text((6, y), "↓ " + down_str, fill=W, font=f_body)
    y += 16
    draw.text((6, y), "↑ " + up_str, fill=W, font=f_body)
    y += 20
    draw.text((6, y), ip, fill=G, font=f_small)
    return img
def main():
    parser = argparse.ArgumentParser(
        description="WeAct Studio 0.96\" USB System Monitor - Cross-platform"
    )
    parser.add_argument("-p", "--port", help="Serial port (auto-detect if omitted)")
    parser.add_argument("-b", "--brightness", type=int, default=80, help="Brightness 0-100 (default: 80)")
    parser.add_argument("-i", "--interval", type=float, default=1.0, help="Update interval seconds (default: 1.0)")
    parser.add_argument("-l", "--list", action="store_true", help="List serial ports and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    if args.list:
        print("Available serial ports:")
        for p in serial.tools.list_ports.comports():
            sn = p.serial_number or "N/A"
            print(f"  {p.device}: {p.description} [VID:{p.vid}, PID:{p.pid}, SN:{sn}]")
        return

    # Find port
    port = find_display_port(args.port)
    if not port:
        log.error("No display found! Use --list to see ports, --port to specify.")
        sys.exit(1)

    log.info(f"Connecting to {port} @ {BAUD_RATE} baud...")

    ser = serial.Serial(port, baudrate=BAUD_RATE, timeout=0.5)
    try:
        # Init
        version = init_display(ser)
        set_brightness(ser, args.brightness)
        log.info(f"Monitor started. Version: {version}, brightness: {args.brightness}%")
        log.info(f"Interval: {args.interval}s. Press Ctrl+C to stop.")

        prev_net = None

        while True:
            loop_start = time.time()

            cpu_pct = get_cpu_percent()
            mem_pct, mem_used, mem_total = get_memory()
            temps = get_temperatures()
            ip = get_host_ip()
            prev_net, up, down = get_network_speed(prev_net, args.interval)

            up_str = format_speed(up)
            down_str = format_speed(down)

            log.debug(f"CPU:{cpu_pct:.0f}% MEM:{mem_pct:.0f}% IP:{ip} v{down_str} ^{up_str}")

            img = render_screen(cpu_pct, mem_pct, ip, up_str, down_str)
            send_bitmap(ser, img)

            elapsed = time.time() - loop_start
            time.sleep(max(0.1, args.interval - elapsed))

    except KeyboardInterrupt:
        log.info("Stopping...")
    except Exception as e:
        log.error(f"Error: {e}", exc_info=args.verbose)
    finally:
        if ser and ser.is_open:
            ser.close()
            log.info("Display closed.")

if __name__ == "__main__":
    main()

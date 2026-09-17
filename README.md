# Head-Mounted FPV Data Logger for Edge AI

A wearable, edge-computed stereo camera system designed to record precise, first-person view (FPV) hand movements. This project generates high-fidelity, synchronized stereo video datasets tailored for imitation learning, behavioral cloning, and robotic AI model training in complex or hazardous environments.

## 🚀 Key Features

* **Global Shutter Precision:** Utilizes the AR0144 sensor to eliminate motion skew during rapid hand movements—a critical requirement for accurate ground-truth spatial data in imitation learning.
* **Headless Edge Operation:** Single-button start/stop control with intelligent RGB LED state feedback (Idle, Recording, Offloading, Error) driven by kernel-level GPIO via `libgpiod`.
* **Autonomous USB Offload:** Custom daemon automatically detects FAT32 USB insertion, securely transfers segmented `.mkv` video files, and flushes hardware buffers without manual intervention.
* **Hardware-Accelerated Encoding:** Leverages a static ARM64 FFmpeg build to bypass legacy dependency conflicts and perform real-time H.264 video compression on resource-constrained embedded systems.

## 🛠️ Hardware & Tech Stack

| Category | Technology |
|---|---|
| **SBCs** | Radxa Zero 3E, Radxa Rock 3C (RK3566) |
| **Camera** | AR0144 Stereo Global Shutter (USB 2.0, 2560×720 @ 30fps or 60 fps) |
| **Languages** | Python 3.9+ |
| **GPIO Control** | `libgpiod` (userspace, hardware-agnostic) |
| **Video Pipeline** | FFmpeg (libx264, H.264 encoding) |
| **System Integration** | Linux `systemd`, `v4l2`, udev |
| **Storage** | FAT32 USB drive, SSD local recordings |

## ⚡ Quick Start

### Prerequisites
```bash
# Install GPIO bindings
sudo apt update && sudo apt install -y gpiod python3-libgpiod

# Download static FFmpeg (avoids legacy repo issues)
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz
tar -xf ffmpeg-release-arm64-static.tar.xz
sudo mv ffmpeg-*-static/ffmpeg /usr/local/bin/ && sudo chmod +x /usr/local/bin/ffmpeg

# Verify installation
ffmpeg -version | head -3
gpioinfo  # List available GPIO chips on your board
```

### Hardware Setup

Connect a **momentary push button** and an **LED (with 150Ω series resistor)** to the GPIO header.

**Identify your GPIO lines:**
```bash
# Find the chip and line numbers for your button and LED pins
gpioinfo | grep GPIO

# Update BUTTON_CHIP, BUTTON_GPIO, LED_CHIP, LED_GPIO in record_camera.py
# based on your board's output (e.g., "GPIO4_A3" → gpiochip4:3)
```

**Example wiring (Radxa Zero 3E):**
```
Button:
  Pin 11 (GPIO4_A3) → Button NO → GND (Pin 9)

LED:
  Pin 16 (GPIO1_B2) → 150Ω Resistor → LED Anode
                                       LED Cathode → GND (Pin 14)
```

### Deploy as systemd Service

```bash
# Copy files to appropriate locations
sudo cp record_camera.py /root/record_camera.py
sudo chmod +x /root/record_camera.py

# Register systemd service
sudo cp camera-recorder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera-recorder.service

# Verify it's running
sudo systemctl status camera-recorder.service

# Watch live logs
sudo journalctl -u camera-recorder.service -f
```

## 📊 Architecture & Workflow

```
AR0144 Camera (MIPI CSI-2)
    ↓
v4l2 /dev/video0 (MJPEG stream)
    ↓
FFmpeg (H.264 encoding, 10-min segments)
    ↓
/home/radxa/Recordings/ (AR0144_YYYYMMDD_HHMMSS.mkv)
    ↓
USB Daemon (idle-time offload)
    ↓
FAT32 USB Drive (backup & post-processing)
```

**Button Controls:**
- **Press:** Toggle recording on/off
- **LED States:**
  - 🟢 Slow blink = Idle, ready to record
  - 🔴 Rapid pulse = Recording in progress
  - 🟡 Solid = USB offload underway
  - ⚪ Fast flash = Error state

## 🎯 Use Cases & Impact

| Domain | Challenge | Solution |
|---|---|---|
| **Hazardous Material Handling** | Safety-critical glovebox tasks; human training slow & risky | Record operator perspective → train robotic arms on exact protocols |
| **Precision Assembly** | PCB soldering, micro-welding; fine motor control hard to program | Capture hand position & tool geometry → behavioral cloning for industrial robots |
| **Heavy Equipment Operation** | Multi-limb coordination (excavators, cranes); operator blind spots | Log lever sequences & spatial reasoning → build autonomous subsystems |
| **Surgical Robotics** | Minimally invasive procedures require instrument coordination | Record surgeon's technique → train robotic surgical assistants |



## 🔧 Configuration

Before running, update these variables in `record_camera.py`:

```python
BUTTON_CHIP = "gpiochip4"  # Your button's GPIO chip (from gpioinfo)
BUTTON_GPIO = 3            # Your button's GPIO line offset
LED_CHIP = "gpiochip1"     # Your LED's GPIO chip
LED_GPIO = 2               # Your LED's GPIO line offset
```

Run `gpioinfo` on your SBC to find the correct values for your specific board.

## 🚨 Common Issues & Fixes

| Issue | Cause | Fix |
|---|---|---|
| `/dev/video0` not found | CSI camera not detected | Reseat CSI cable; check kernel logs: `dmesg \| grep camera` |
| LED doesn't light | Wrong GPIO chip/line OR LED polarity reversed | Verify with `gpioinfo`; test with manual GPIO toggle |
| FFmpeg I/O error | v4l2 format mismatch or camera unstable | Power cycle SBC; test: `v4l2-ctl -d /dev/video0 --list-formats-ext` |
| USB offload stalls | FAT32 not mounted OR /Recordings owned by root | Format USB: `sudo mkfs.vfat -F 32 /dev/sdb1`; verify owner: `ls -la /home/radxa/Recordings` |
| High CPU / dropped frames | ultrafast preset too aggressive | Reduce preset to "superfast"; or reduce resolution/FPS |

**For detailed troubleshooting,** see `TROUBLESHOOTING.md`.

## 🎓 Learning Resources

* **AR0144 Datasheet:** https://www.onsemi.com/pub/Collateral/AR0144-D.PDF
* **libgpiod Documentation:** https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git/plain/README
* **FFmpeg H.264 Encoding:** https://trac.ffmpeg.org/wiki/Encode/H.264
* **Imitation Learning Survey:** https://arxiv.org/abs/1703.02702 (Ross et al., 2017)

## 📋 License

Distributed under the **MIT License**. See `LICENSE` file for full details.

## 👤 Author

**Gautam Sharma**  


---

**Last Updated:** September 17, 2025 | **Status:** Production-Ready

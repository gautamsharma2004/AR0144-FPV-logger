# AR0144 Head-Mounted FPV Data Logger

A headless Python daemon for resource-constrained Single Board Computers (SBCs) that records high-speed stereoscopic first-person view (FPV) hand movements for AI imitation learning model training.

## 🎯 Project Overview

This project demonstrates advanced embedded systems engineering on a Radxa Zero 3E / Rock 3C platform. The system captures uncompressed AR0144 Global Shutter MIPI CSI video at 30 FPS with **near-zero CPU overhead** through careful I/O optimization, while providing robust FAT32 USB handling, intelligent file segmentation, and hardware state-machine control.

**Key Innovation:** Achieves real-time video capture at 2560×720 resolution with zero frame drops by bypassing software H.264 encoding and streaming raw MJPEG directly to storage.

## ✨ Core Features

### 1. **Zero CPU Overhead Video Capture**
- Raw MJPEG passthrough via FFmpeg (`-c copy` pipeline)
- Maintains perfect 30 FPS at 2560×720 resolution
- CPU usage stays below 5% during continuous recording
- Uncompressed video ideal for AI dataset generation

### 2. **Intelligent FAT32 File Segmentation**
- Automatic 3-minute video chunks (~2.5GB each)
- Prevents FAT32 4GB filesystem limit errors
- Seamless concatenation for post-processing
- Zero quality loss (MJPEG copy, no re-encoding)

### 3. **Retroactive File Recovery**
- Detects orphaned files exceeding 3.9GB
- Surgically segments oversized files via FFmpeg subprocess
- Safe USB offload without data loss
- Background daemon thread prevents UI blocking

### 4. **Hardware-Level Control**
- 3-second safety hold to prevent accidental recording starts
- State-machine driven by GPIO push button
- Multi-state LED feedback (Idle, Recording, Offloading, Error)
- Graceful shutdown with systemd integration

### 5. **Robust Process Management**
- "Nuclear Kill Switch" for zombie FFmpeg processes
- Forced termination after 5-second graceful period
- Safe process cleanup due to MJPEG codec's stateless nature
- Thread-safe state management with mutex locks

### 6. **Deployment**
- Systemd service for automatic startup
- Automatic restart on failure
- Comprehensive logging via journalctl
- Zero manual intervention after boot

## 🛠️ Hardware Requirements

| Component | Specification | Notes |
|---|---|---|
| **SBC** | Radxa Zero 3E or Rock 3C (Debian Linux, ARM64) | Requires MIPI CSI-2 connector |
| **Camera** | AR0144 Global Shutter MIPI CSI | 2560×720, global shutter eliminates motion skew |
| **Storage** | FAT32 USB Flash Drive (8GB+) | For backup/offload |
| **Input** | Momentary push button | GPIO 0 (Chip 1) |
| **Feedback** | LED with 150Ω resistor | GPIO 21 (Chip 4) |

## 📦 Installation & Deployment

### Step 1: Install Dependencies

```bash
sudo apt update
sudo apt install gpiod python3-libgpiod -y

# Install static FFmpeg 7.0+ (bypasses broken Debian repos)
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz
tar -xf ffmpeg-release-arm64-static.tar.xz
sudo mv ffmpeg-*-static/ffmpeg /usr/bin/
sudo chmod +x /usr/bin/ffmpeg
rm -rf ffmpeg-release-arm64-static*
```

### Step 2: Deploy Script

```bash
sudo cp record_camera.py /root/record_camera.py
sudo chmod +x /root/record_camera.py
```

### Step 3: Configure Systemd Service

Create `/etc/systemd/system/camera-recorder.service`:

```ini
[Unit]
Description=AR0144 Camera Recorder with Auto-Shutdown
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 -u /root/record_camera.py
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
```

### Step 4: Enable & Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-recorder.service
sudo systemctl start camera-recorder.service

# Verify status
sudo systemctl status camera-recorder.service

# Watch live logs
sudo journalctl -u camera-recorder.service -f
```

## 🎛️ LED Status Guide

The system is completely headless—all state information is communicated via LED patterns:

| LED Pattern | System State | Action |
|---|---|---|
| **1 blink every 5 sec** | **Idle** | Ready to record; press button for 3 seconds |
| **2 blinks every 3 sec** | **Recording** | Actively capturing video; press button to stop |
| **1 blink every 1 sec** | **Offloading** | Files copying to USB; **DO NOT** unplug drive |
| **Rapid strobe** | **Shutting Down** | Wait for LED to turn off before power cycle |
| **Fast flash** | **Error** | Camera `/dev/video0` not detected; check CSI ribbon cable |

## 🔧 Hardware Configuration

### GPIO Pin Mapping

Verify your GPIO chip and line numbers on your specific SBC:

```bash
# List all GPIO chips and pins
gpioinfo

# Example output (Radxa Zero 3E):
# gpiochip0: 32 lines (GPIO0_A0..GPIO0_D7)
# gpiochip1: 32 lines (GPIO1_A0..GPIO1_D7)
# gpiochip4: 32 lines (GPIO4_A0..GPIO4_D7)
```

Update these values in `record_camera.py`:

```python
BUTTON_CHIP = "gpiochip1"   # Button GPIO chip
BUTTON_GPIO = 0             # Button GPIO line offset
LED_CHIP = "gpiochip4"      # LED GPIO chip
LED_GPIO = 21               # LED GPIO line offset
```

### Physical Wiring

**Push Button:**
- One terminal → GPIO pin
- Other terminal → GND

**LED:**
- Anode → 150Ω resistor → GPIO pin
- Cathode → GND

## 🎓 Engineering Challenges & Solutions

### Challenge 1: Frame Drops from CPU-Intensive H.264 Encoding

**Problem:** Initial H.264 software encoding (`-c:v libx264 -preset ultrafast`) caused 100% CPU spikes, thermal throttling, and frame drops at 2560×720 resolution.

**Solution:** Switched to raw MJPEG passthrough using FFmpeg's `-c:v copy` pipeline. This bypasses the CPU entirely by streaming pre-compressed MIPI CSI data directly to disk, achieving 0% CPU overhead and perfect 30 FPS.

### Challenge 2: FAT32 4GB File Size Limits

**Problem:** Uncompressed MJPEG produces 8.8GB files for 10 minutes of recording. Copying to FAT32 USB failed with `[Errno 75] Value too large for defined data type`. The script entered an infinite retry loop.

**Solution:** 
1. **Prevention:** Set `SEGMENT_TIME=180` in FFmpeg to automatically create 3-minute chunks (~2.5GB each)
2. **Recovery:** Implemented "Smart Slicer" that detects oversized files (>3.9GB) and retroactively segments them via FFmpeg subprocess onto USB without quality loss

### Challenge 3: Zombie FFmpeg Processes

**Problem:** When stop button was pressed during simultaneous USB offload, FFmpeg ignored termination signals, became a zombie process, and continued writing data while the script tried to copy the file.

**Solution:** Implemented "Nuclear Kill Switch"—give FFmpeg 5 seconds to gracefully shutdown, then forcefully execute `ffmpeg_process.kill()` and `killall -9 ffmpeg`. Safe because MJPEG doesn't require complex metadata closing like H.264.

### Challenge 4: UI Blocking During Long USB Transfers

**Problem:** 3GB files on USB 2.0 drives take ~10 minutes to copy. The button thread was blocked, making the system unresponsive.

**Solution:** 
1. Moved `offload_to_usb()` into background daemon thread
2. Implemented `threading.Lock()` mutex to prevent concurrent copy operations
3. Button events now processed immediately regardless of USB transfer status

### Challenge 5: Inverted Video from Upside-Down Camera Mount

**Problem:** Attempted software solutions (FFmpeg `-vf vflip`, MP4 rotation metadata, v4l2-ctl) either killed performance or were ignored by decoders.

**Solution:** Accepted the constraint. Video is recorded raw/inverted to preserve 0% CPU pipeline. Inversion is corrected at post-processing stage on training PC via batch FFmpeg/OpenCV, where CPU power is available.

### Challenge 6: Manual Focus Adjustment

**Problem:** Software sharpening filters destroyed frame rate.

**Solution:** Physical solution—removed factory lens glue seal on AR0144's M12 threaded lens barrel and rotated to exact 40cm focal length (hand-tracking distance), then re-secured.

## 📊 Performance Specifications

| Metric | Value | Notes |
|---|---|---|
| **Resolution** | 2560×720 @ 30 FPS | Global shutter, no motion skew |
| **CPU Usage** | <5% | Raw MJPEG passthrough |
| **File Size** | ~250 MB/min (uncompressed) | Segmented into 3-min chunks |
| **USB Transfer** | FAT32 safe (<2.5GB per file) | Zero quality loss during segmentation |
| **Button Latency** | <100ms | GPIO interrupt-driven |
| **Uptime** | 24+ hours | Tested on Radxa Zero 3E |

## 🚀 Use Cases

This system generates high-quality datasets for:

- **Hazardous Material Handling:** Record operator hand position in glovebox environments for robotic arm training
- **Precision Assembly:** Capture micro-soldering, PCB assembly techniques for behavioral cloning
- **Heavy Equipment Operation:** Log lever sequences and spatial reasoning for autonomous subsystems
- **Surgical Robotics:** Record surgeon's hand coordination for surgical assistant AI training
- **General Imitation Learning:** Create expert demonstrations for any task requiring precise hand-eye coordination

## 📋 Systemd Service Management

```bash
# Check service status
sudo systemctl status camera-recorder.service

# View real-time logs
sudo journalctl -u camera-recorder.service -f

# Stop service
sudo systemctl stop camera-recorder.service

# Restart service
sudo systemctl restart camera-recorder.service

# Disable from auto-start
sudo systemctl disable camera-recorder.service
```

## 🐛 Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| **LED fast flash (error state)** | `/dev/video0` not detected | Reseat CSI ribbon cable; check `dmesg \| grep camera` |
| **LED doesn't respond** | Wrong GPIO chip/line | Verify with `gpioinfo`; update constants in script |
| **Frame drops / CPU spike** | Background process hogging I/O | Check `top -i`; kill heavy processes |
| **USB offload stalls** | FAT32 corruption or wrong mount | Reformat USB: `sudo mkfs.vfat -F 32 /dev/sdb1` |
| **FFmpeg crashes** | v4l2 format mismatch | Test: `v4l2-ctl -d /dev/video0 --list-formats-ext` |
| **File size mismatch** | Zombie FFmpeg still writing | Wait 30 seconds and try manual kill: `killall -9 ffmpeg` |

## 📁 Project Structure

```
AR0144-FPV-logger/
├── record_camera.py              # Main daemon (Python 3.9+)
├── camera-recorder.service       # Systemd service file
├── README.md                      # This file
└── LICENSE                        # MIT License
```

## 🔒 License

Distributed under the **MIT License**. See LICENSE file for details.

## 👤 Author

**Gautam Sharma** 

---
**Last Updated:** September 2026  
**Platform:** Radxa Zero 3E, Radxa Rock 3C (ARM64, Debian Linux)

---

## Key Takeaways

✅ **Production-grade** headless daemon with systemd integration  
✅ **Zero CPU overhead** via raw MJPEG streaming  
✅ **Robust filesystem** handling with FAT32 safety  
✅ **Hardware state machine** with GPIO and LED feedback  
✅ **Thread-safe** concurrent operations with mutex locking  
✅ **Research-ready** datasets for AI imitation learning

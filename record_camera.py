#!/usr/bin/env python3
import functools
print = functools.partial(print, flush=True)
import subprocess
import signal
import sys
import os
import time
import threading
import shutil
import gpiod

VIDEO_DEVICE = "/dev/video0"
WIDTH = 2560
HEIGHT = 720
FPS = 30
SEGMENT_TIME = 600
RECORDING_DIR = "/home/radxa/Recordings"
BUTTON_CHIP = "gpiochip1"
BUTTON_GPIO = 0
LED_CHIP = "gpiochip4"
LED_GPIO = 21
LED_RECORD_INTERVAL = 2.0
LED_RECORD_ON_TIME = 0.15
LED_ERROR_INTERVAL = 0.15
LED_IDLE_INTERVAL = 0.2

running = True
recording_enabled = False
recording_failed = False
is_offloading = False
ffmpeg_process = None
state_lock = threading.Lock()

os.makedirs(RECORDING_DIR, exist_ok=True)

print("=" * 70)
print("     AR0144 CAMERA RECORDER - RADXA ZERO 3E")
print("=" * 70)

button_chip = None
led_chip = None
button_line = None
led_line = None

try:
    button_chip = gpiod.Chip(BUTTON_CHIP)
    led_chip = gpiod.Chip(LED_CHIP)
    button_line = button_chip.get_line(BUTTON_GPIO)
    led_line = led_chip.get_line(LED_GPIO)
    button_line.request(consumer="ar0144-button", type=gpiod.LINE_REQ_DIR_IN, flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP)
    led_line.request(consumer="ar0144-led", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
    print("✓ GPIO initialized successfully\n")
except Exception as error:
    print(f"✗ GPIO initialization failed: {error}")
    sys.exit(1)

def led_on():
    try: led_line.set_value(1)
    except: pass

def led_off():
    try: led_line.set_value(0)
    except: pass

def led_controller():
    while running:
        try:
            with state_lock:
                enabled = recording_enabled
                failed = recording_failed
                offloading = is_offloading

            if failed:
                led_on(); time.sleep(LED_ERROR_INTERVAL)
                led_off(); time.sleep(LED_ERROR_INTERVAL)
            elif offloading:
                # Solid LED while offloading to USB
                led_on(); time.sleep(0.5)
            elif enabled:
                # Rapid blink when RECORDING
                led_on(); time.sleep(0.2)
                led_off(); time.sleep(0.2)
            else:
                # Slow blink when IDLE (glows every 2 seconds)
                led_on(); time.sleep(0.15)
                led_off(); time.sleep(2.0)
        except Exception as e:
            print(f"[LED] Error: {e}")
            time.sleep(1)

def get_usb_mount_point():
    """Dynamically finds or forcibly mounts an inserted USB drive."""
    # 1. Check if already mounted by the OS
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                if line.startswith('/dev/sd'):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1] # Returns the existing mount path
    except Exception as e:
        print(f"[USB] Error reading mounts: {e}")
        
    # 2. If physically plugged in but NOT mounted, mount it ourselves
    import glob
    partitions = glob.glob('/dev/sd*[0-9]') # Looks for /dev/sda1, etc.
    if partitions:
        device = partitions[0]
        mount_path = "/media/usb"
        print(f"[USB] Unmounted drive {device} detected. Mounting to {mount_path}...")
        try:
            os.makedirs(mount_path, exist_ok=True)
            # The service runs as root, so this mount command will succeed
            subprocess.run(['mount', device, mount_path], check=True)
            return mount_path
        except Exception as e:
            print(f"[USB] Mount failed. Is it formatted correctly? Error: {e}")
            
    return None

def get_recordings():
    files = []
    try:
        for filename in os.listdir(RECORDING_DIR):
            if filename.startswith("AR0144_") and filename.endswith(".mkv"):
                path = os.path.join(RECORDING_DIR, filename)
                if os.path.isfile(path):
                    files.append(path)
    except:
        pass
    files.sort(key=os.path.getmtime)
    return files

def offload_to_usb():
    global is_offloading
    
    usb_path = get_usb_mount_point()
    if not usb_path:
        print("[USB] No USB drive detected. Files will remain on device.")
        return

    recordings = get_recordings()
    if not recordings:
        print("[USB] No recordings found to offload.")
        return

    with state_lock:
        is_offloading = True

    print(f"[USB] USB DETECTED at: {usb_path}")
    
    for source in recordings:
        filename = os.path.basename(source)
        target = os.path.join(usb_path, filename) # Directly to root of USB

        try:
            file_size_mb = os.path.getsize(source) / (1024*1024)
            print(f"[USB] Copying: {filename} ({file_size_mb:.1f}MB)")
            
            # shutil.copy2 preserves metadata
            shutil.copy2(source, target)
            
            # Verify file size before deleting the original
            if os.path.getsize(source) == os.path.getsize(target):
                os.remove(source)
                print(f"[USB] ✓ Copied and deleted: {filename}")
            else:
                print(f"[USB] ✗ Size mismatch, original kept: {filename}")
        except Exception as e:
            print(f"[USB] ✗ Error copying {filename}: {e}")
            
    with state_lock:
        is_offloading = False
def usb_monitor():
    while running:
        try:
            with state_lock:
                enabled = recording_enabled
                offloading = is_offloading
            
            # Only check if camera is completely idle
            if not enabled and not offloading:
                # Only search for USB if there are actually files waiting on the SD card
                if get_recordings(): 
                    if get_usb_mount_point():
                        print("[USB] Pending files and USB detected. Starting late offload...")
                        offload_to_usb()
        except Exception as e:
            pass
        time.sleep(10)

def start_recording():
    global ffmpeg_process, recording_failed
    
    if not os.path.exists(VIDEO_DEVICE):
        print(f"[RECORD] ERROR: {VIDEO_DEVICE} does not exist!")
        with state_lock: recording_failed = True
        return
        
    OUTPUT_PATTERN = os.path.join(RECORDING_DIR, "AR0144_%Y%m%d_%H%M%S.mkv")
    command = ["ffmpeg", "-loglevel", "warning", "-f", "v4l2", "-input_format", "mjpeg", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS), "-i", VIDEO_DEVICE,"-vf", "vflip,hflip", "-c:v", "libx264", "-preset", "ultrafast", "-f", "segment", "-segment_time", str(SEGMENT_TIME), "-reset_timestamps", "1", "-strftime", "1", OUTPUT_PATTERN]
    
    try:
        ffmpeg_process = subprocess.Popen(command)
        print(f"[RECORD] Started FFmpeg (PID: {ffmpeg_process.pid})")
    except Exception as error:
        print(f"✗ Recording error: {error}")
        with state_lock: recording_failed = True
        ffmpeg_process = None

def stop_recording():
    global ffmpeg_process
    if ffmpeg_process is None: return
    
    print(f"[RECORD] Stopping FFmpeg (PID: {ffmpeg_process.pid})")
    try:
        ffmpeg_process.send_signal(signal.SIGINT)
        ffmpeg_process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        ffmpeg_process.terminate()
    ffmpeg_process = None
    print("✓ Recording stopped")

def toggle_recording():
    global recording_enabled, recording_failed
    
    with state_lock: enabled = recording_enabled
    
    if enabled:
        print("\n[BUTTON] Recording OFF")
        with state_lock:
            recording_enabled = False
            recording_failed = False
        stop_recording()
        time.sleep(1) # Give filesystem a moment to sync
        print("[USB] Starting USB offload...")
        offload_to_usb()
    else:
        print("\n[BUTTON] Recording ON")
        with state_lock:
            recording_enabled = True
            recording_failed = False
        start_recording()

def button_monitor():
    last_state = 1
    debounce = 0.05
    while running:
        try:
            current_state = button_line.get_value()
            if last_state == 1 and current_state == 0:
                time.sleep(debounce)
                if button_line.get_value() == 0:
                    toggle_recording()
                    # Wait for button release
                    while button_line.get_value() == 0 and running:
                        time.sleep(0.01)
            last_state = current_state
        except Exception as error:
            print(f"[BUTTON] Error: {error}")
            time.sleep(1)
        time.sleep(0.01)

def stop_manager(signal_number=None, frame=None):
    global running
    print("\nSHUTTING DOWN")
    running = False
    with state_lock: recording_enabled = False
    stop_recording()
    led_off()
    try:
        button_line.release()
        led_line.release()
        button_chip.close()
        led_chip.close()
    except: pass
    sys.exit(0)

# Re-enabled signal handlers for systemd compatibility
signal.signal(signal.SIGINT, stop_manager)
signal.signal(signal.SIGTERM, stop_manager)

threading.Thread(target=led_controller, daemon=True).start()
threading.Thread(target=button_monitor, daemon=True).start()
threading.Thread(target=usb_monitor, daemon=True).start()
print("✓ Ready")
print("LED: Blink=Idle, Rapid=Recording, Solid=Offloading, Fast=Error")

try:
    while running:
        time.sleep(1)
except KeyboardInterrupt:
    stop_manager()
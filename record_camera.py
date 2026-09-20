import functools
print = functools.partial(print, flush=True)
import subprocess
import signal
import sys
import os
import time
import threading
import shutil
import glob
import gpiod

VIDEO_DEVICE = "/dev/video0"
WIDTH = 2560
HEIGHT = 720
FPS = 30
# 180 seconds (3 mins) prevents future files from exceeding the FAT32 4GB limit
SEGMENT_TIME = 180  
RECORDING_DIR = "/home/radxa/Recordings"
BUTTON_CHIP = "gpiochip1"
BUTTON_GPIO = 0
LED_CHIP = "gpiochip4"
LED_GPIO = 21

running = True
recording_enabled = False
recording_failed = False
is_offloading = False
is_shutting_down = False
ffmpeg_process = None
state_lock = threading.Lock()

os.makedirs(RECORDING_DIR, exist_ok=True)

print("=" * 70)
print("     AR0144 CAMERA RECORDER - RADXA ZERO 3E / 3C")
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
                shutting_down = is_shutting_down

            if shutting_down:
                # Rapid blink during shutdown: 100ms ON / 100ms OFF
                led_on(); time.sleep(0.1)
                led_off(); time.sleep(0.1)
            elif failed:
                # Error state: fast flash
                led_on(); time.sleep(0.15)
                led_off(); time.sleep(0.15)
            elif offloading:
                # Offloading: 500ms ON / 500ms OFF (1 blink per second)
                led_on(); time.sleep(0.5)
                led_off(); time.sleep(0.5)
            elif enabled:
                # Recording: 2 blinks every 3 seconds
                led_on(); time.sleep(0.5)
                led_off(); time.sleep(0.2)
                led_on(); time.sleep(0.5)
                led_off(); time.sleep(1.8)
            else:
                # Idle on boot: 1 blink (800ms) every 5 seconds
                led_on(); time.sleep(0.8)
                led_off(); time.sleep(4.2)
        except Exception as e:
            print(f"[LED] Error: {e}")
            time.sleep(1)

def get_usb_mount_point():
    """Dynamically finds or forcibly mounts an inserted USB drive."""
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                if line.startswith('/dev/sd'):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
    except: pass
        
    partitions = glob.glob('/dev/sd*[0-9]')
    if partitions:
        device = partitions[0]
        mount_path = "/media/usb"
        print(f"[USB] Unmounted drive {device} detected. Mounting to {mount_path}...")
        try:
            os.makedirs(mount_path, exist_ok=True)
            subprocess.run(['mount', device, mount_path], check=True)
            return mount_path
        except Exception as e:
            print(f"[USB] Mount failed. Error: {e}")
            
    return None

def get_recordings():
    files = []
    try:
        for filename in os.listdir(RECORDING_DIR):
            if filename.startswith("AR0144_") and filename.endswith(".mkv"):
                path = os.path.join(RECORDING_DIR, filename)
                if os.path.isfile(path):
                    files.append(path)
    except: pass
    files.sort(key=os.path.getmtime)
    return files

def offload_to_usb():
    global is_offloading, is_shutting_down
    
    # PREVENT OVERLAPPING COPIES
    with state_lock:
        if is_offloading: return
        is_offloading = True
        
    try:
        usb_path = get_usb_mount_point()
        if not usb_path:
            print("[USB] No USB drive detected. Files will remain on device.")
            return

        recordings = get_recordings()
        if not recordings:
            print("[USB] No recordings found to offload.")
            return

        print(f"\n[USB] USB DETECTED at: {usb_path}")
        error_occurred = False
        
        for source in recordings:
            filename = os.path.basename(source)
            target = os.path.join(usb_path, filename)

            try:
                file_size_bytes = os.path.getsize(source)
                file_size_mb = file_size_bytes / (1024*1024)
                
                # FAT32 Safe Limit (3.9 GB)
                FAT32_LIMIT = 3.9 * 1024 * 1024 * 1024 
                
                if file_size_bytes > FAT32_LIMIT:
                    print(f"[USB] {filename} ({file_size_mb:.1f}MB) exceeds FAT32 limits!")
                    print(f"[USB] Slicing {filename} directly to USB to bypass limit safely...")
                    
                    base = os.path.splitext(filename)[0]
                    ext = os.path.splitext(filename)[1]
                    target_pattern = os.path.join(usb_path, f"{base}_part%03d{ext}")
                    
                    split_cmd = [
                        "ffmpeg", "-loglevel", "error", "-y",
                        "-i", source,
                        "-c", "copy", # Retains raw quality, zero loss
                        "-f", "segment",
                        "-segment_time", "180",
                        "-reset_timestamps", "1",
                        target_pattern
                    ]
                    
                    # Split and offload directly to USB
                    subprocess.run(split_cmd, check=True)
                    os.sync()
                    
                    # If ffmpeg successfully completes the split without crashing:
                    os.remove(source)
                    print(f"[USB] ✓ Successfully sliced, offloaded, and deleted original: {filename}")

                else:
                    # Normal copy for safe < 4GB files
                    print(f"[USB] Copying: {filename} ({file_size_mb:.1f}MB)")
                    shutil.copy2(source, target)
                    os.sync() 
                    
                    if os.path.getsize(source) == os.path.getsize(target):
                        os.remove(source)
                        print(f"[USB] ✓ Copied and deleted: {filename}")
                    else:
                        print(f"[USB] ✗ Size mismatch, original kept: {filename}")
                        error_occurred = True

            except subprocess.CalledProcessError:
                print(f"[USB] ✗ FFmpeg split failed (USB full?). Original kept: {filename}")
                error_occurred = True
            except Exception as e:
                print(f"[USB] ✗ Error copying {filename}: {e}")
                error_occurred = True

        # Check if we successfully emptied the recording folder
        remaining_files = get_recordings()
        if not remaining_files and not error_occurred:
            print("\n[SYSTEM] All files offloaded successfully.")
            print("[SYSTEM] Initiating smooth shutdown...")
            with state_lock:
                is_shutting_down = True
            os.system("shutdown -h now")

    finally:
        # GUARANTEE THE LOCK IS RELEASED
        with state_lock:
            is_offloading = False

def usb_monitor():
    while running:
        try:
            with state_lock:
                enabled = recording_enabled
                offloading = is_offloading
            
            if not enabled and not offloading:
                if get_recordings(): 
                    if get_usb_mount_point():
                        print("[USB] Pending files and USB detected. Starting late offload...")
                        offload_to_usb()
        except: pass
        time.sleep(10)

def start_recording():
    global ffmpeg_process, recording_failed
    
    if not os.path.exists(VIDEO_DEVICE):
        print(f"[RECORD] ERROR: {VIDEO_DEVICE} does not exist!")
        with state_lock: recording_failed = True
        return
        
    OUTPUT_PATTERN = os.path.join(RECORDING_DIR, "AR0144_%Y%m%d_%H%M%S.mkv")
    
    # SMOOTH MJPEG COMMAND - Bypasses CPU encoding, Raw MJPEG format, No Inverts
    command = [
        "ffmpeg", "-loglevel", "warning", 
        "-f", "v4l2", 
        "-input_format", "mjpeg", 
        "-video_size", f"{WIDTH}x{HEIGHT}", 
        "-framerate", str(FPS), 
        "-i", VIDEO_DEVICE, 
        "-c:v", "copy", 
        "-f", "segment", 
        "-segment_time", str(SEGMENT_TIME), 
        "-reset_timestamps", "1", 
        "-strftime", "1", 
        OUTPUT_PATTERN
    ]
    
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
        ffmpeg_process.wait(timeout=5) # 5 Second Failsafe
    except subprocess.TimeoutExpired:
        print("[RECORD] FFmpeg hanging. Forcing instant kill...")
        ffmpeg_process.kill() 
        ffmpeg_process.wait()
        
    os.system("killall -9 ffmpeg 2>/dev/null")
    ffmpeg_process = None
    print("✓ Recording stopped")

def button_monitor():
    global recording_enabled, recording_failed
    last_state = 1
    
    while running:
        try:
            current_state = button_line.get_value()
            
            # Detect falling edge (button pressed down)
            if last_state == 1 and current_state == 0:
                time.sleep(0.05) # Debounce
                
                if button_line.get_value() == 0:
                    press_start = time.time()
                    triggered_start = False
                    
                    # While button is actively being held down
                    while button_line.get_value() == 0 and running:
                        with state_lock: enabled = recording_enabled
                        hold_duration = time.time() - press_start
                        
                        # 3-Second Hold Logic (Start Recording)
                        if not enabled and hold_duration >= 3.0 and not triggered_start:
                            print("\n[BUTTON] 3-second hold detected. Recording ON")
                            with state_lock:
                                recording_enabled = True
                                recording_failed = False
                            start_recording()
                            triggered_start = True # Prevent multiple triggers
                            
                        time.sleep(0.05)
                    
                    # Button has been released
                    release_duration = time.time() - press_start
                    with state_lock: enabled = recording_enabled
                    
                    # Short Press Logic (Stop Recording)
                    if enabled and not triggered_start and release_duration >= 0.05:
                        print("\n[BUTTON] Button pressed. Recording OFF")
                        with state_lock:
                            recording_enabled = False
                            recording_failed = False
                        stop_recording()
                        
                        time.sleep(1) 
                        print("[USB] Checking for offload...")
                        threading.Thread(target=offload_to_usb, daemon=True).start()

            last_state = current_state
        except Exception as error:
            print(f"[BUTTON] Error: {error}")
            time.sleep(1)
        time.sleep(0.01)

def stop_manager(signal_number=None, frame=None):
    global running
    
    with state_lock:
        shutting_down = is_shutting_down
        
    if shutting_down and signal_number == signal.SIGTERM:
        return

    print("\nSHUTTING DOWN SCRIPT")
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

# Register signal handlers
signal.signal(signal.SIGINT, stop_manager)
signal.signal(signal.SIGTERM, stop_manager)

threading.Thread(target=led_controller, daemon=True).start()
threading.Thread(target=button_monitor, daemon=True).start()
threading.Thread(target=usb_monitor, daemon=True).start()
print("✓ Ready")

try:
    while running:
        time.sleep(1)
except KeyboardInterrupt:
    stop_manager()

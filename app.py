import RPi.GPIO as gpio
import pigpio
import time
from flask import Flask, Response, render_template_string, request
from picamera2 import Picamera2, Preview
import cv2
import numpy as np
import os
import threading

app = Flask(__name__)

# --- Camera Setup ---
picam2 = Picamera2()
camera_config = picam2.create_video_configuration(main={"size": (1024, 760)})
picam2.configure(camera_config)
picam2.start()

# --- GPIO and Motor Setup ---
DIR_PIN_1 = 20
STEP_PIN_1 = 21
DIR_PIN_2 = 22
STEP_PIN_2 = 23
STEP_DELAY = 0.0001

SOLINOID_PIN = 17
SOLINOID_PIN_2 = 18
gpio.setmode(gpio.BCM)
gpio.setup(SOLINOID_PIN, gpio.OUT)
gpio.setup(SOLINOID_PIN_2, gpio.OUT)
gpio.output(SOLINOID_PIN, gpio.LOW)
gpio.output(SOLINOID_PIN_2, gpio.LOW)
SOLINOID_SET_TIME = .02
SOLINOID_PULSE_TIME = .02

# --- Global State ---
PAN_POSITION = 0
TILT_POSITION = 0
PAN_MIN = -2000
PAN_MAX = 2000
TILT_MIN = -800
TILT_MAX = 1000

MOTION_DETECTION_PAUSE_UNTIL = 0
DETECTION_PAUSE_AFTER_MOVE = 2.0
PIXELS_PER_STEP_PAN = 1
PIXELS_PER_STEP_TILT = 1
MOTION_AREA_THRESHOLD = 350
AUTO_MOTION_ENABLED = False
AUTO_FIRE_ENABLED = False
PRE_MOVE_PAUSE_TIME = 0.0
MANUAL_OVERRIDE_PAUSE_UNTIL = 0
AUTO_SCAN_ENABLED = False
AUTO_SCAN_WAIT = 15
MOTION_CONSECUTIVE_FRAMES = 2
motion_consecutive_count = 0
last_motion_box = None
CONSECUTIVE_MOTION_DETECTION_BUFFER = 1.5  # 50% larger region

# --- pigpio Setup ---
pi = pigpio.pi()
if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon")

def initialize_steppers():
    pi.set_mode(DIR_PIN_1, pigpio.OUTPUT)
    pi.set_mode(STEP_PIN_1, pigpio.OUTPUT)
    pi.write(DIR_PIN_1, 0)
    pi.set_mode(DIR_PIN_2, pigpio.OUTPUT)
    pi.set_mode(STEP_PIN_2, pigpio.OUTPUT)
    pi.write(DIR_PIN_2, 0)

def rotate_motor(dir_pin, step_pin, steps, clockwise=True):
    global MOTION_DETECTION_PAUSE_UNTIL
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE
    pi.write(dir_pin, 1 if clockwise else 0)
    for _ in range(steps):
        pi.write(step_pin, 1)
        time.sleep(STEP_DELAY)
        pi.write(step_pin, 0)
        time.sleep(STEP_DELAY)
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE

# --- Solenoid Functions ---
def solinoid_off():
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.HIGH)
    time.sleep(SOLINOID_SET_TIME)
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)

def solinoid_on():
    gpio.output(SOLINOID_PIN, gpio.HIGH)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)
    time.sleep(SOLINOID_SET_TIME)
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)

def solinoid_pulse():
    solinoid_on()
    time.sleep(SOLINOID_PULSE_TIME)
    solinoid_off()

def solinoid_auto(number):
    for _ in range(number):
        solinoid_pulse()
        time.sleep(.1)

# --- Pan/Tilt Movement Functions ---
def step_servo_pan(direction, fine=False):
    global PAN_POSITION, MOTION_DETECTION_PAUSE_UNTIL
    steps = 100
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE
    if direction == "right":
        if PAN_POSITION - steps >= PAN_MIN:
            rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps, clockwise=False)
            PAN_POSITION -= steps
        else:
            PAN_POSITION = PAN_MIN
    elif direction == "left":
        if PAN_POSITION + steps <= PAN_MAX:
            rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps, clockwise=True)
            PAN_POSITION += steps
        else:
            PAN_POSITION = PAN_MAX
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE

def step_servo_tilt(direction, fine=False):
    global TILT_POSITION, MOTION_DETECTION_PAUSE_UNTIL
    steps = 100
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE
    if direction == "up":
        if TILT_POSITION + steps <= TILT_MAX:
            rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps, clockwise=True)
            TILT_POSITION += steps
        else:
            TILT_POSITION = TILT_MAX
    elif direction == "down":
        if TILT_POSITION - steps >= TILT_MIN:
            rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps, clockwise=False)
            TILT_POSITION -= steps
        else:
            TILT_POSITION = TILT_MIN
    MOTION_DETECTION_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE

def move_to_target(target_x, target_y, center_x, center_y):
    global PAN_POSITION, TILT_POSITION
    offset_x = target_x - center_x
    offset_y = target_y - center_y
    steps_pan = int(abs(offset_x) / PIXELS_PER_STEP_PAN)
    steps_tilt = int(abs(offset_y) / PIXELS_PER_STEP_TILT)
    if steps_pan > 0:
        if offset_x > 0:
            rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=False)
            PAN_POSITION = max(PAN_MIN, PAN_POSITION - steps_pan)
        else:
            rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=True)
            PAN_POSITION = min(PAN_MAX, PAN_POSITION + steps_pan)
    if steps_tilt > 0:
        if offset_y > 0:
            rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=False)
            TILT_POSITION = max(TILT_MIN, TILT_POSITION - steps_tilt)
        else:
            rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=True)
            TILT_POSITION = min(TILT_MAX, TILT_POSITION + steps_tilt)

# --- Motion Detection Logic ---
def detect_motion(prev_gray, frame, threshold):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    
    # Mask out high-brightness pixels (e.g., > 230)
    brightness_mask = (gray < 230).astype(np.uint8)  # 1 where not too bright, 0 where too bright
    masked_gray = gray * brightness_mask
    masked_prev = prev_gray * brightness_mask
    frame_delta = cv2.absdiff(masked_prev, masked_gray)
    thresh = cv2.threshold(frame_delta, 3, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    motion_boxes = []
    max_area = 0
    max_box = None
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < threshold:
            continue
        (x, y, w, h) = cv2.boundingRect(contour)
        motion_boxes.append((x, y, w, h))
        if area > max_area:
            max_area = area
            max_box = (x, y, w, h)
    return gray, motion_boxes, max_box

# --- Frame Generation ---
def draw_overlays(frame, width, height, center_x, center_y):
    # Pan line and triangle
    line_y = int(height * 0.05)
    line_x1 = int(width * 0.25)
    line_x2 = int(width * 0.75)
    line_color = (0, 255, 0)
    line_thickness = 3
    cv2.line(frame, (line_x1, line_y), (line_x2, line_y), line_color, line_thickness)
    pan_range = PAN_MAX - PAN_MIN
    if pan_range == 0:
        pan_pos_x = line_x1
    else:
        pan_pos_x = int(line_x1 + (PAN_MAX - PAN_POSITION) / pan_range * (line_x2 - line_x1))
    pan_pos_x = max(line_x1, min(pan_pos_x, line_x2))
    triangle_height = 16
    triangle_half_width = 8
    pts = np.array([
        [pan_pos_x, line_y + triangle_height],
        [pan_pos_x - triangle_half_width, line_y],
        [pan_pos_x + triangle_half_width, line_y],
    ], np.int32)
    cv2.fillPoly(frame, [pts], line_color)

    # Tilt line and triangle
    tilt_line_x = int(width * 0.05)
    tilt_line_y1 = int(height * 0.10)
    tilt_line_y2 = int(height * 0.90)
    cv2.line(frame, (tilt_line_x, tilt_line_y1), (tilt_line_x, tilt_line_y2), line_color, line_thickness)
    tilt_range = TILT_MAX - TILT_MIN
    if tilt_range == 0:
        tilt_pos_y = tilt_line_y2
    else:
        tilt_pos_y = int(tilt_line_y1 + (TILT_MAX - TILT_POSITION) / tilt_range * (tilt_line_y2 - tilt_line_y1))
    tilt_pos_y = max(tilt_line_y1, min(tilt_pos_y, tilt_line_y2))
    tilt_triangle_height = 16
    tilt_triangle_half_width = 8
    tilt_pts = np.array([
        [tilt_line_x, tilt_pos_y],
        [tilt_line_x - tilt_triangle_height, tilt_pos_y - tilt_triangle_half_width],
        [tilt_line_x - tilt_triangle_height, tilt_pos_y + tilt_triangle_half_width],
    ], np.int32)
    cv2.fillPoly(frame, [tilt_pts], line_color)

    # Motion area threshold square
    square_side = int(MOTION_AREA_THRESHOLD ** 0.5)
    top_left = (center_x - square_side // 2, center_y - square_side // 2)
    bottom_right = (center_x + square_side // 2, center_y + square_side // 2)
    yellow = (0, 255, 255)
    cv2.rectangle(frame, top_left, bottom_right, yellow, 2)

    # Crosshairs and dots
    crosshair_length = 40
    dot_radius = 4
    color = (0, 255, 0)
    thickness = 2
    cv2.line(frame, (center_x - crosshair_length, center_y), (center_x + crosshair_length, center_y), color, thickness)
    cv2.line(frame, (center_x, center_y - crosshair_length), (center_x, center_y + crosshair_length), color, thickness)
    for offset in [0, crosshair_length // 3, 2 * crosshair_length // 3]:
        if offset == 0:
            cv2.circle(frame, (center_x, center_y), dot_radius, color, -1)
        else:
            cv2.circle(frame, (center_x - offset, center_y), dot_radius, color, -1)
            cv2.circle(frame, (center_x + offset, center_y), dot_radius, color, -1)
            cv2.circle(frame, (center_x, center_y - offset), dot_radius, color, -1)
            cv2.circle(frame, (center_x, center_y + offset), dot_radius, color, -1)

    # Label
    label = "Garden Protectron 2000"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    font_thickness = 2
    text_size, _ = cv2.getTextSize(label, font, font_scale, font_thickness)
    text_x = (width - text_size[0]) // 2
    text_y = int(height * (.95)) + text_size[1] // 2
    cv2.putText(frame, label, (text_x, text_y), font, font_scale, (0, 255, 0), font_thickness, cv2.LINE_AA)

    # Pan/tilt position
    pos_text = f"Pan: {PAN_POSITION}"
    tilt_text = f"Tilt: {TILT_POSITION}"
    font_scale = 0.7
    font_thickness = 1
    text_color = (0, 255, 0)
    margin = 20
    pos_size, _ = cv2.getTextSize(pos_text, font, font_scale, font_thickness)
    tilt_size, _ = cv2.getTextSize(tilt_text, font, font_scale, font_thickness)
    pos_x = width - pos_size[0] - margin
    tilt_x = width - tilt_size[0] - margin
    pos_y = 40
    tilt_y = pos_y + pos_size[1] + 10
    cv2.putText(frame, pos_text, (pos_x, pos_y), font, font_scale, text_color, font_thickness, cv2.LINE_AA)
    cv2.putText(frame, tilt_text, (tilt_x, tilt_y), font, font_scale, text_color, font_thickness, cv2.LINE_AA)

    # Auto scan countdown
    if AUTO_SCAN_ENABLED:
        seconds_until_scan = int(max(0, auto_scan_next_time - time.time()))
        scan_text = f"Next scan move: {seconds_until_scan}s"
        scan_font_scale = 0.7
        scan_font_thickness = 1
        scan_color = (0, 255, 255)
        scan_size, _ = cv2.getTextSize(scan_text, font, scan_font_scale, scan_font_thickness)
        scan_x = width - scan_size[0] - margin
        scan_y = tilt_y + tilt_size[1] + 15
        cv2.putText(frame, scan_text, (scan_x, scan_y), font, scan_font_scale, scan_color, scan_font_thickness, cv2.LINE_AA)

def gen_frames():
    global motion_consecutive_count, last_motion_box

    if not hasattr(gen_frames, "prev_gray"):
        gen_frames.prev_gray = None
    if not hasattr(gen_frames, "target_motion_box"):
        gen_frames.target_motion_box = None
    if not hasattr(gen_frames, "target_motion_box_visible"):
        gen_frames.target_motion_box_visible = False
    if not hasattr(gen_frames, "move_in_progress"):
        gen_frames.move_in_progress = False
    if not hasattr(gen_frames, "pause_until"):
        gen_frames.pause_until = 0

    global auto_scan_next_time
    if 'auto_scan_next_time' not in globals():
        auto_scan_next_time = time.time() + 15

    while True:
        frame = picam2.capture_array()
        height, width, _ = frame.shape
        center_x, center_y = width // 2, height // 2

        # Motion detection should use a clean frame (no overlays)
        frame_for_motion = frame.copy()

        # Convert frame to grayscale for motion detection
        if gen_frames.prev_gray is None:
            gray = cv2.cvtColor(frame_for_motion, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            gen_frames.prev_gray = gray
            motion_boxes = []
        else:
            now = time.time()
            auto_motion_active = AUTO_MOTION_ENABLED and (now > MANUAL_OVERRIDE_PAUSE_UNTIL)
            auto_fire_active = AUTO_FIRE_ENABLED and (now > MANUAL_OVERRIDE_PAUSE_UNTIL)
            # Disable motion detection during and after any move
            if gen_frames.move_in_progress or now < gen_frames.pause_until or now < MOTION_DETECTION_PAUSE_UNTIL:
                gray = cv2.cvtColor(frame_for_motion, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                gen_frames.prev_gray = gray
                motion_boxes = []
                motion_consecutive_count = 0
                last_motion_box = None
            else:
                gray, motion_boxes, max_box = detect_motion(gen_frames.prev_gray, frame_for_motion, MOTION_AREA_THRESHOLD)
                gen_frames.prev_gray = gray

                if max_box is not None:
                    x, y, w, h = max_box
                    # If the box is similar to the last, increment, else reset
                    if last_motion_box is not None:
                        lx, ly, lw, lh = last_motion_box
                        # Define a buffer region 50% larger than the last box
                        buffer_w = int(lw * CONSECUTIVE_MOTION_DETECTION_BUFFER)
                        buffer_h = int(lh * CONSECUTIVE_MOTION_DETECTION_BUFFER)
                        buffer_x = lx + lw // 2 - buffer_w // 2
                        buffer_y = ly + lh // 2 - buffer_h // 2
                        # Check if the current box is inside the buffered region
                        in_buffer = (
                            x >= buffer_x and
                            y >= buffer_y and
                            x + w <= buffer_x + buffer_w and
                            y + h <= buffer_y + buffer_h
                        )
                        if in_buffer:
                            motion_consecutive_count += 1
                        else:
                            motion_consecutive_count = 1
                    else:
                        motion_consecutive_count = 1
                    last_motion_box = max_box

                    x, y, w, h = max_box
                    # Draw light green box for any motion
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (144, 238, 144), 3)

                    # If 5+ consecutive frames, draw red box and save image
                    if motion_consecutive_count >= MOTION_CONSECUTIVE_FRAMES:
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 3)
                        side = max(w, h)
                        cx = x + w // 2
                        cy = y + h // 2
                        half_side = side // 2
                        crop_x1 = max(0, cx - half_side)
                        crop_y1 = max(0, cy - half_side)
                        crop_x2 = min(width, cx + half_side)
                        crop_y2 = min(height, cy + half_side)
                        if crop_x2 > crop_x1 and crop_y2 > crop_y1:
                            crop = frame_for_motion[crop_y1:crop_y2, crop_x1:crop_x2]
                            folder = os.path.join("motion_images", str(MOTION_AREA_THRESHOLD))
                            os.makedirs(folder, exist_ok=True)
                            timestamp = int(time.time() * 1000)
                            filename = os.path.join(folder, f"motion_{timestamp}.png")
                            cv2.imwrite(filename, crop)
                else:
                    # No motion detected, reset counter and box
                    motion_consecutive_count = 0
                    last_motion_box = None

                # Only perform auto-move if enabled and not in manual override pause
                if auto_motion_active:
                    if not gen_frames.target_motion_box and motion_boxes:
                        gen_frames.target_motion_box = max(motion_boxes, key=lambda b: b[2]*b[3])
                        gen_frames.target_motion_box_visible = True

                    if getattr(gen_frames, "target_motion_box", None) and getattr(gen_frames, "target_motion_box_visible", False):
                        x, y, w, h = gen_frames.target_motion_box
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 3)

                    if gen_frames.target_motion_box:
                        gen_frames.move_in_progress = True
                        pause_start = time.time()
                        while time.time() - pause_start < PRE_MOVE_PAUSE_TIME:
                            x, y, w, h = gen_frames.target_motion_box
                            frame_copy = frame.copy()
                            cv2.rectangle(frame_copy, (x, y), (x + w, y + h), (0, 0, 255), 3)
                            ret, buffer = cv2.imencode('.jpg', frame_copy)
                            if not ret:
                                continue
                            frame_bytes = buffer.tobytes()
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

                        gen_frames.target_motion_box_visible = False
                        x, y, w, h = gen_frames.target_motion_box
                        target_x = x + w // 2
                        target_y = y + h // 2
                        move_to_target(target_x, target_y, center_x, center_y)
                        gen_frames.target_motion_box = None
                        gen_frames.move_in_progress = False
                        gen_frames.pause_until = time.time() + DETECTION_PAUSE_AFTER_MOVE
                        if auto_fire_active:
                            solinoid_auto(3)
        
        # Draw overlays for user display
        draw_overlays(frame, width, height, center_x, center_y)

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# --- Flask Routes ---
HTML_PAGE = """
    <html>
    <head>
    <title>Garden Protectron 2000</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
    body {
        -webkit-touch-callout: none;
        -webkit-text-size-adjust: none;
        display: flex;
        flex-direction: row; /* Arrange items horizontally */
        height: 100vh; /* Occupy full viewport height */
        margin: 0;
        font-size: 1.5em; /* Make text bigger */
    }
    .video-container {
        width: 66%; /* Video takes up 2/3 of the screen */
        display: flex;
        justify-content: center;
        align-items: center;
    }
    .controls-container {
        width: 34%; /* Controls take up remaining 1/3 */
        display: flex;
        flex-direction: column;
        justify-content: space-around; /* Distribute buttons evenly */
        align-items: center;
    }
    .arrow-buttons {
        display: grid;
        grid-template-columns: repeat(3, 1fr); /* Three columns */
        grid-template-rows: repeat(3, 1fr);    /* Three rows */
        gap: 0.1em;                             /* Spacing between buttons */
        width: 100%;                            /* Take up full width of container */
        max-width: 300px;                       /* Limit the width of the grid */
    }
    .arrow-buttons button {
        font-size: 1em;
        padding: 0.5em;
        border-radius: 0.5em;
        background-color: #4CAF50; /* Green */
        color: white;
        border: none;
        cursor: pointer;
    }
    .arrow-buttons button:hover {
        background-color: #3e8e41;
    }
    /* Positioning the buttons in the grid */
    .arrow-up {
        grid-column: 2; /* Center column */
        grid-row: 1;    /* Top row */
    }
    .arrow-left {
        grid-column: 1; /* Left column */
        grid-row: 2;    /* Middle row */
    }
    .arrow-right {
        grid-column: 3; /* Right column */
        grid-row: 2;    /* Middle row */
    }
    .arrow-down {
        grid-column: 2; /* Center column */
        grid-row: 3;    /* Bottom row */
    }
    img {
        max-width: 100%;
        max-height: 100%;
    }
    button {
        font-size: 1em; /* Bigger buttons */
        padding: 0.5em 1em;
        margin: 0.5em;
        border-radius: 0.5em;
    }
    .reset-center {
        grid-column: 2;
        grid-row: 2;
        background-color: #2196F3;
    }
    .reset-center:hover {
        background-color: #1769aa;
    }
    </style>
    </head>
    <body>
    <div class="video-container">
        <img src="{{ url_for('video_feed') }}">
    </div>
    <div class="controls-container">
        <div class="arrow-buttons">
            <button class="arrow-up" onclick="fetch('/tilt_step?direction=up')">&#8593;</button>
            <button class="arrow-left" onclick="fetch('/pan_step?direction=left')">&#8592;</button>
            <button class="reset-center" onclick="fetch('/calibrate_pan_tilt')">&#9679;</button>
            <button class="arrow-right" onclick="fetch('/pan_step?direction=right')">&#8594;</button>
            <button class="arrow-down" onclick="fetch('/tilt_step?direction=down')">&#8595;</button>
        </div>
        <button onclick="fetch('/solinoid_pulse')">Single Fire</button>
        <button onclick="fetch('/solinoid_auto3')">Pulse Fire</button>
    <div>
        <label for="motion-threshold">Motion Area Threshold: <span id="threshold-value">{{ threshold }}</span></label>
        <input type="range" min="50" max="5000" value="{{ threshold }}" id="motion-threshold" step="100" 
               oninput="document.getElementById('threshold-value').innerText=this.value"
               onchange="fetch('/set_motion_threshold?value='+this.value)">
    </div>
    <div>
        <label for="motion-pause">Pause Detection After Move (s): <span id="pause-value">{{ pause_time }}</span></label>
        <input type="range" min="0" max="3" value="{{ pause_time }}" id="motion-pause" step="0.1"
               oninput="document.getElementById('pause-value').innerText=this.value"
               onchange="fetch('/set_detection_pause_after_move?value='+this.value)">
    </div>
    <div>
        <label for="pre-move-pause">Pause Before Auto Move (s): <span id="pre-move-pause-value">{{ pre_move_pause_time }}</span></label>
        <input type="range" min="0" max="2" value="{{ pre_move_pause_time }}" id="pre-move-pause" step="0.1"
               oninput="document.getElementById('pre-move-pause-value').innerText=this.value"
               onchange="fetch('/set_pre_move_pause?value='+this.value)">
    </div>
    <div>
        <label for="auto-scan-wait">Auto Pan Timer (s): <span id="auto-scan-wait-value">{{ auto_scan_wait }}</span></label>
        <input type="range" min="5" max="60" value="{{ auto_scan_wait }}" id="auto-scan-wait" step="1"
               oninput="document.getElementById('auto-scan-wait-value').innerText=this.value"
               onchange="fetch('/set_auto_scan_wait?value='+this.value)">
    </div>
    <div>
        <label for="auto-motion">Auto Center on Movement:</label>
        <button id="auto-motion-btn" onclick="toggleAutoMotion()">{{ 'ON' if auto_motion else 'OFF' }}</button>
    </div>
    <div>
        <label for="auto-fire">Auto Fire:</label>
        <button id="auto-fire-btn" onclick="toggleAutoFire()">{{ 'ON' if auto_fire else 'OFF' }}</button>
    </div>
    <div>
        <label for="auto-scan">Auto Scan:</label>
        <button id="auto-scan-btn" onclick="toggleAutoScan()">{{ 'ON' if auto_scan else 'OFF' }}</button>
    </div>
    </div>
    <script>
    function toggleAutoMotion() {
        fetch('/toggle_auto_motion')
          .then(() => location.reload());
    }
    function toggleAutoFire() {
        fetch('/toggle_auto_fire')
          .then(() => location.reload());
    }
    function toggleAutoScan() {
        fetch('/toggle_auto_scan')
          .then(() => location.reload());
    }
    </script>
    </body>
    </html>
    """

@app.route('/')
def index():
    return render_template_string(
        HTML_PAGE,
        threshold=MOTION_AREA_THRESHOLD,
        pause_time=DETECTION_PAUSE_AFTER_MOVE,
        pre_move_pause_time=PRE_MOVE_PAUSE_TIME,
        auto_motion=AUTO_MOTION_ENABLED,
        auto_fire=AUTO_FIRE_ENABLED,
        auto_scan=AUTO_SCAN_ENABLED,
        auto_scan_wait=AUTO_SCAN_WAIT
    )

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/pan_step')
def pan_step_route():
    global MANUAL_OVERRIDE_PAUSE_UNTIL
    direction = request.args.get('direction')
    fine = request.args.get('fine') == 'true'
    if direction in ["left", "right"]:
        step_servo_pan(direction, fine)
        MANUAL_OVERRIDE_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE
    return ("", 204)

@app.route('/tilt_step')
def tilt_step_route():
    global MANUAL_OVERRIDE_PAUSE_UNTIL
    direction = request.args.get('direction')
    fine = request.args.get('fine') == 'true'
    if direction in ["up", "down"]:
        step_servo_tilt(direction, fine)
        MANUAL_OVERRIDE_PAUSE_UNTIL = time.time() + DETECTION_PAUSE_AFTER_MOVE
    return ("", 204)

@app.route('/solinoid_pulse')
def solinoid_pulse_route():
    solinoid_pulse()
    return ("", 204)

@app.route('/solinoid_auto3')
def solinoid_auto3_route():
    solinoid_auto(3)
    return ("", 204)

@app.route('/set_motion_threshold')
def set_motion_threshold():
    global MOTION_AREA_THRESHOLD
    try:
        value = int(request.args.get('value', 5000))
        MOTION_AREA_THRESHOLD = max(50, min(value, 5000))
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_detection_pause_after_move')
def set_detection_pause_after_move():
    global DETECTION_PAUSE_AFTER_MOVE
    try:
        value = float(request.args.get('value', 2.0))
        DETECTION_PAUSE_AFTER_MOVE = max(0, min(value, 3))
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_pre_move_pause')
def set_pre_move_pause():
    global PRE_MOVE_PAUSE_TIME
    try:
        value = float(request.args.get('value', 0.0))
        PRE_MOVE_PAUSE_TIME = max(0, min(value, 2))
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_auto_scan_wait')
def set_auto_scan_wait():
    global AUTO_SCAN_WAIT
    try:
        value = int(request.args.get('value', 15))
        AUTO_SCAN_WAIT = max(5, min(value, 60))
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/toggle_auto_motion')
def toggle_auto_motion():
    global AUTO_MOTION_ENABLED
    AUTO_MOTION_ENABLED = not AUTO_MOTION_ENABLED
    return ("", 204)

@app.route('/toggle_auto_fire')
def toggle_auto_fire():
    global AUTO_FIRE_ENABLED
    AUTO_FIRE_ENABLED = not AUTO_FIRE_ENABLED
    return ("", 204)

@app.route('/toggle_auto_scan')
def toggle_auto_scan():
    global AUTO_SCAN_ENABLED
    AUTO_SCAN_ENABLED = not AUTO_SCAN_ENABLED
    return ("", 204)

@app.route('/calibrate_pan_tilt')
def calibrate_pan_tilt():
    global PAN_POSITION, TILT_POSITION
    PAN_POSITION = 0
    TILT_POSITION = 0
    return ("", 204)

# --- Auto Scan Thread ---
def auto_scan_thread():
    global PAN_POSITION, AUTO_SCAN_ENABLED, auto_scan_next_time, AUTO_SCAN_WAIT, MOTION_DETECTION_PAUSE_UNTIL, DETECTION_PAUSE_AFTER_MOVE
    scan_direction = -1
    PAN_STEP = 800
    while True:
        if AUTO_SCAN_ENABLED:
            next_pos = PAN_POSITION + (PAN_STEP * scan_direction)
            if scan_direction == -1 and next_pos < PAN_MIN:
                next_pos = PAN_MIN
            elif scan_direction == 1 and next_pos > PAN_MAX:
                next_pos = PAN_MAX
            steps = abs(PAN_POSITION - next_pos)
            clockwise = (next_pos > PAN_POSITION)
            if steps > 0:
                move_time = steps * STEP_DELAY * 2
                MOTION_DETECTION_PAUSE_UNTIL = time.time() + move_time + DETECTION_PAUSE_AFTER_MOVE
                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps, clockwise=clockwise)
                PAN_POSITION = next_pos
            auto_scan_next_time = time.time() + AUTO_SCAN_WAIT
            time.sleep(AUTO_SCAN_WAIT)
            if PAN_POSITION == PAN_MIN or PAN_POSITION == PAN_MAX:
                scan_direction *= -1
        else:
            auto_scan_next_time = time.time() + 1
            time.sleep(1)

threading.Thread(target=auto_scan_thread, daemon=True).start()

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        pi.stop()
        picam2.close()
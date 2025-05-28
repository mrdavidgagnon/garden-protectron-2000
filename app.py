import RPi.GPIO as gpio
import pigpio
import time
from flask import Flask, Response, render_template_string, request
from picamera2 import Picamera2, Preview
import cv2
import numpy as np
import os

app = Flask(__name__)

# Initialize Picamera2
picam2 = Picamera2()
camera_config = picam2.create_video_configuration(main={"size": (1024, 760)})
picam2.configure(camera_config)
picam2.start()

# GPIO pin configuration for Motor 1 PAN
DIR_PIN_1 = 20  # Direction pin for Motor 1
STEP_PIN_1 = 21  # Step pin for Motor 1

# GPIO pin configuration for Motor 2 TILT
DIR_PIN_2 = 22  # Direction pin ßfor Motor 2
STEP_PIN_2 = 23  # Step pin for Motor 2
STEP_DELAY =  0.0001  # Delay between steps in seconds

# Solinoid setup 
SOLINOID_PIN = 17  # Replace with the GPIO pin connected to your solenoid
SOLINOID_PIN_2 = 18
# Initialize GPIO
gpio.setmode(gpio.BCM)
gpio.setup(SOLINOID_PIN, gpio.OUT)
gpio.setup(SOLINOID_PIN_2, gpio.OUT)
gpio.output(SOLINOID_PIN, gpio.LOW)  # Set the solenoid to LOW (off)    
gpio.output(SOLINOID_PIN_2, gpio.LOW)  # Set the solenoid to LOW (off)   
SOLINOID_SET_TIME = .02  # Time in seconds to set the solenoid
SOLINOID_PULSE_TIME = .02  # Time in seconds to set the solenoid

# Add these global variables to track pan and tilt position (in steps)
PAN_POSITION = 0
TILT_POSITION = 0

# Set pan limits (move to global scope for reuse)
PAN_MIN = -2000
PAN_MAX = 2000

# Set tilt limits (move to global scope for reuse)
TILT_MIN = -800
TILT_MAX = 1000


# Initialize pigpio
pi = pigpio.pi()
if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon")

# Function to initialize the stepper drivers
def initialize_steppers():
    # Motor 1
    pi.set_mode(DIR_PIN_1, pigpio.OUTPUT)
    pi.set_mode(STEP_PIN_1, pigpio.OUTPUT)
    pi.write(DIR_PIN_1, 0)  # Set default direction for Motor 1

    # Motor 2
    pi.set_mode(DIR_PIN_2, pigpio.OUTPUT)
    pi.set_mode(STEP_PIN_2, pigpio.OUTPUT)
    pi.write(DIR_PIN_2, 0)  # Set default direction for Motor 2

# Function to rotate a motor
def rotate_motor(dir_pin, step_pin, steps, clockwise=True):
    pi.write(dir_pin, 1 if clockwise else 0)  # Set direction
    for _ in range(steps):
        pi.write(step_pin, 1)
        time.sleep(STEP_DELAY)
        pi.write(step_pin, 0)
        time.sleep(STEP_DELAY)

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
    for i in range(number):
        solinoid_pulse()
        time.sleep(.1)


def step_servo_pan(direction, fine=False):
    global PAN_POSITION
    steps = 100

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

def step_servo_tilt(direction, fine=False):
    global TILT_POSITION
    steps = 100

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

# Global variable for motion area threshold (default 2750)
MOTION_AREA_THRESHOLD = 2750

# Calibration: how many pixels in the image correspond to one step of the motor
PIXELS_PER_STEP_PAN = 1   # Adjust experimentally
PIXELS_PER_STEP_TILT = 1  # Adjust experimentally

# Add this global variable for the pause time (in seconds) after centering on motion
MOTION_PAUSE_TIME = 2.0  # Default 2 seconds

# Add this global variable to enable/disable auto movement
AUTO_MOTION_ENABLED = False  # "Auto Center on Movement" mode

# Add this global variable to enable/disable auto fire after auto movement
AUTO_FIRE_ENABLED = False

# Add this global variable for the pause time (in seconds) before starting auto move
PRE_MOVE_PAUSE_TIME = 0.0  # Default pause before auto move (seconds)

# Add this global variable to pause auto features during manual override
MANUAL_OVERRIDE_PAUSE_UNTIL = 0  # Timestamp until which auto features are paused

# Add this global variable for auto scan mode
AUTO_SCAN_ENABLED = False

# Add this global variable for auto scan wait time (default 15 seconds)
AUTO_SCAN_WAIT = 15

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
        <label for="motion-pause">Pause After Centering (s): <span id="pause-value">{{ pause_time }}</span></label>
        <input type="range" min="0" max="3" value="{{ pause_time }}" id="motion-pause" step="0.1"
               oninput="document.getElementById('pause-value').innerText=this.value"
               onchange="fetch('/set_motion_pause?value='+this.value)">
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


def gen_frames():
    global PAN_POSITION, PAN_MIN, PAN_MAX, TILT_POSITION, TILT_MIN, TILT_MAX, MANUAL_OVERRIDE_PAUSE_UNTIL
    if not hasattr(gen_frames, "move_in_progress"):
        gen_frames.move_in_progress = False
    if not hasattr(gen_frames, "target_motion_box"):
        gen_frames.target_motion_box = None
    if not hasattr(gen_frames, "pause_until"):
        gen_frames.pause_until = 0

    # --- Add access to auto_scan_thread's scan_wait and next scan time ---
    # Use a global to track the next scan time
    global auto_scan_next_time
    if 'auto_scan_next_time' not in globals():
        auto_scan_next_time = time.time() + 15  # Default to 15s from now

    while True:
        frame = picam2.capture_array()
        height, width, _ = frame.shape
        center_x, center_y = width // 2, height // 2

        # --- Draw pan range line and current position triangle ---
        line_y = int(height * 0.05)
        # Only use the middle 50% of the screen for the line (leaving 25% margin on each side)
        line_x1 = int(width * 0.25)
        line_x2 = int(width * 0.75)
        line_color = (0, 255, 0)
        line_thickness = 3

        # Draw the pan range line
        cv2.line(frame, (line_x1, line_y), (line_x2, line_y), line_color, line_thickness)

        # Map PAN_POSITION to the line
        pan_range = PAN_MAX - PAN_MIN
        if pan_range == 0:
            pan_pos_x = line_x1
        else:
            # When PAN_POSITION == PAN_MAX, pan_pos_x == line_x1 (left edge)
            # When PAN_POSITION == PAN_MIN, pan_pos_x == line_x2 (right edge)
            pan_pos_x = int(
                line_x1 + (PAN_MAX - PAN_POSITION) / (PAN_MAX - PAN_MIN) * (line_x2 - line_x1)
            )
        pan_pos_x = max(line_x1, min(pan_pos_x, line_x2))

        # Draw a small green triangle for current pan position
        triangle_height = 16
        triangle_half_width = 8
        pts = np.array([
            [pan_pos_x, line_y + triangle_height],  # bottom point
            [pan_pos_x - triangle_half_width, line_y],  # left point
            [pan_pos_x + triangle_half_width, line_y],  # right point
        ], np.int32)
        cv2.fillPoly(frame, [pts], line_color)

        # --- Draw tilt range line and current position triangle ---
        # Vertical line on the left 5% of the video
        tilt_line_x = int(width * 0.05)
        tilt_line_y1 = int(height * 0.10)  # 10% from top
        tilt_line_y2 = int(height * 0.90)  # 10% from bottom

        # Draw the tilt range line
        cv2.line(frame, (tilt_line_x, tilt_line_y1), (tilt_line_x, tilt_line_y2), line_color, line_thickness)

        # Map TILT_POSITION to the line
        tilt_range = TILT_MAX - TILT_MIN
        if tilt_range == 0:
            tilt_pos_y = tilt_line_y2
        else:
            # When TILT_POSITION == TILT_MAX, tilt_pos_y == tilt_line_y1 (top)
            # When TILT_POSITION == TILT_MIN, tilt_pos_y == tilt_line_y2 (bottom)
            tilt_pos_y = int(
                tilt_line_y1 + (TILT_MAX - TILT_POSITION) / (TILT_MAX - TILT_MIN) * (tilt_line_y2 - tilt_line_y1)
            )
        tilt_pos_y = max(tilt_line_y1, min(tilt_pos_y, tilt_line_y2))

        # Draw a small green triangle for current tilt position (pointing right at the line)
        tilt_triangle_height = 16
        tilt_triangle_half_width = 8
        tilt_pts = np.array([
            [tilt_line_x, tilt_pos_y],  # tip at the line
            [tilt_line_x - tilt_triangle_height, tilt_pos_y - tilt_triangle_half_width],  # upper left
            [tilt_line_x - tilt_triangle_height, tilt_pos_y + tilt_triangle_half_width],  # lower left
        ], np.int32)
        cv2.fillPoly(frame, [tilt_pts], line_color)

        # --- Draw yellow square for motion area threshold in the center ---
        # Calculate the side length of the square so that its area equals MOTION_AREA_THRESHOLD
        square_side = int(MOTION_AREA_THRESHOLD ** 0.5)
        top_left = (center_x - square_side // 2, center_y - square_side // 2)
        bottom_right = (center_x + square_side // 2, center_y + square_side // 2)
        yellow = (0, 255, 255)
        cv2.rectangle(frame, top_left, bottom_right, yellow, 2)

        # --- Existing overlays (crosshairs, label, pan/tilt text, etc.) ---
        crosshair_length = 40
        dot_radius = 4
        color = (0, 255, 0)
        thickness = 2
        # Horizontal lineß
        cv2.line(frame, (center_x - crosshair_length, center_y), (center_x + crosshair_length, center_y), color, thickness)
        # Vertical line
        cv2.line(frame, (center_x, center_y - crosshair_length), (center_x, center_y + crosshair_length), color, thickness)
        # Mil dots: center and at 1/3 and 2/3 of crosshair length from center
        for offset in [0, crosshair_length // 3, 2 * crosshair_length // 3]:
            if offset == 0:
                cv2.circle(frame, (center_x, center_y), dot_radius, color, -1)
            else:
                cv2.circle(frame, (center_x - offset, center_y), dot_radius, color, -1)
                cv2.circle(frame, (center_x + offset, center_y), dot_radius, color, -1)
                cv2.circle(frame, (center_x, center_y - offset), dot_radius, color, -1)
                cv2.circle(frame, (center_x, center_y + offset), dot_radius, color, -1)

        # Superimpose centered green text label at the bottom 5% of the frame
        label = "Garden Protectron 2000"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_thickness = 2
        text_size, _ = cv2.getTextSize(label, font, font_scale, font_thickness)
        text_x = (width - text_size[0]) // 2
        text_y = int(height * (.95)) + text_size[1] // 2
        cv2.putText(frame, label, (text_x, text_y), font, font_scale, (0, 255, 0), font_thickness, cv2.LINE_AA)

        # Overlay pan/tilt position in the top right corner, small green Courier font
        pos_text = f"Pan: {PAN_POSITION}"
        tilt_text = f"Tilt: {TILT_POSITION}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        font_thickness = 1
        text_color = (0, 255, 0)

        # Calculate positions for right-aligned text
        margin = 20
        pos_size, _ = cv2.getTextSize(pos_text, font, font_scale, font_thickness)
        tilt_size, _ = cv2.getTextSize(tilt_text, font, font_scale, font_thickness)
        pos_x = width - pos_size[0] - margin
        tilt_x = width - tilt_size[0] - margin
        pos_y = 40
        tilt_y = pos_y + pos_size[1] + 10

        cv2.putText(frame, pos_text, (pos_x, pos_y), font, font_scale, text_color, font_thickness, cv2.LINE_AA)
        cv2.putText(frame, tilt_text, (tilt_x, tilt_y), font, font_scale, text_color, font_thickness, cv2.LINE_AA)

        # --- Overlay: Auto Scan countdown (under pan/tilt) ---
        if AUTO_SCAN_ENABLED:
            # Show seconds until next scan move
            seconds_until_scan = int(max(0, auto_scan_next_time - time.time()))
            scan_text = f"Next scan move: {seconds_until_scan}s"
            scan_font_scale = 0.7
            scan_font_thickness = 1
            scan_color = (0, 255, 255)  # Yellow
            scan_size, _ = cv2.getTextSize(scan_text, font, scan_font_scale, scan_font_thickness)
            scan_x = width - scan_size[0] - margin
            scan_y = tilt_y + tilt_size[1] + 15
            cv2.putText(frame, scan_text, (scan_x, scan_y), font, scan_font_scale, scan_color, scan_font_thickness, cv2.LINE_AA)

        # Convert frame to grayscale for motion detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        now = time.time()
        # Disable auto features if manual override pause is active
        auto_motion_active = AUTO_MOTION_ENABLED and (now > MANUAL_OVERRIDE_PAUSE_UNTIL)
        auto_fire_active = AUTO_FIRE_ENABLED and (now > MANUAL_OVERRIDE_PAUSE_UNTIL)
        if not hasattr(gen_frames, "prev_gray"):
            gen_frames.prev_gray = gray
            motion_boxes = []
        else:
            if gen_frames.move_in_progress or now < gen_frames.pause_until:
                gen_frames.prev_gray = gray
            else:
                frame_delta = cv2.absdiff(gen_frames.prev_gray, gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)

                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                motion_boxes = []
                max_area = 0
                max_box = None
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area < MOTION_AREA_THRESHOLD:
                        continue
                    (x, y, w, h) = cv2.boundingRect(contour)
                    motion_boxes.append((x, y, w, h))
                    if area > max_area:
                        max_area = area
                        max_box = (x, y, w, h)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3)

                # --- Save the most significant motion as a PNG square image ---
                if max_box is not None:
                    x, y, w, h = max_box
                    # Make a square crop around the motion area
                    side = max(w, h)
                    cx = x + w // 2
                    cy = y + h // 2
                    half_side = side // 2
                    # Ensure the crop is within image bounds
                    crop_x1 = max(0, cx - half_side)
                    crop_y1 = max(0, cy - half_side)
                    crop_x2 = min(width, cx + half_side)
                    crop_y2 = min(height, cy + half_side)
                    crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]

                    # Prepare folder and filename
                    folder = os.path.join("motion_images", str(MOTION_AREA_THRESHOLD))
                    os.makedirs(folder, exist_ok=True)
                    timestamp = int(time.time() * 1000)
                    filename = os.path.join(folder, f"motion_{timestamp}.png")
                    cv2.imwrite(filename, crop)

                # Only perform auto-move if enabled and not in manual override pause
                if auto_motion_active:
                    # If not already tracking a target, pick the largest box as the target
                    if not gen_frames.target_motion_box and motion_boxes:
                        gen_frames.target_motion_box = max(motion_boxes, key=lambda b: b[2]*b[3])
                        gen_frames.target_motion_box_visible = True  # Show the red box

                    # Draw the target box in red if it exists and is visible
                    if getattr(gen_frames, "target_motion_box", None) and getattr(gen_frames, "target_motion_box_visible", False):
                        x, y, w, h = gen_frames.target_motion_box
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 3)

                    # If we have a target, move to center on it and ignore all other motion until done
                    if gen_frames.target_motion_box:
                        gen_frames.move_in_progress = True  # Set flag before moving

                        # Pause before starting auto movement, but keep updating the camera feed
                        pause_start = time.time()
                        while time.time() - pause_start < PRE_MOVE_PAUSE_TIME:
                            # Draw the red box during the pause
                            x, y, w, h = gen_frames.target_motion_box
                            frame_copy = frame.copy()
                            cv2.rectangle(frame_copy, (x, y), (x + w, y + h), (0, 0, 255), 3)

                            # Encode and yield the frame with the red box
                            ret, buffer = cv2.imencode('.jpg', frame_copy)
                            if not ret:
                                continue
                            frame_bytes = buffer.tobytes()
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

                        # Hide the red box after the pause and before moving
                        gen_frames.target_motion_box_visible = False

                        x, y, w, h = gen_frames.target_motion_box
                        target_x = x + w // 2
                        target_y = y + h // 2

                        offset_x = target_x - center_x
                        offset_y = target_y - center_y

                        steps_pan = int(abs(offset_x) / PIXELS_PER_STEP_PAN)
                        steps_tilt = int(abs(offset_y) / PIXELS_PER_STEP_TILT)

                        # Move pan (left/right) and update PAN_POSITION within limits
                        if steps_pan > 0:
                            if offset_x > 0:
                                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=False)
                                PAN_POSITION = max(PAN_MIN, PAN_POSITION - steps_pan)
                            else:
                                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=True)
                                PAN_POSITION = min(PAN_MAX, PAN_POSITION + steps_pan)

                        # Move tilt (up/down) and update TILT_POSITION within limits
                        if steps_tilt > 0:
                            if offset_y > 0:
                                rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=False)
                                TILT_POSITION = max(TILT_MIN, TILT_POSITION - steps_tilt)
                            else:
                                rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=True)
                                TILT_POSITION = min(TILT_MAX, TILT_POSITION + steps_tilt)

                        # After moving, clear the target and pause further tracking
                        gen_frames.target_motion_box = None
                        gen_frames.move_in_progress = False
                        gen_frames.pause_until = time.time() + MOTION_PAUSE_TIME

                        # Fire the solenoid 3 times after centering on motion, only if auto fire is enabled and not in manual override pause
                        if auto_fire_active:
                            solinoid_auto(3)

                gen_frames.prev_gray = gray

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue
        frame_bytes = buffer.tobytes()

        # Render as an HTTP multipart response
        # This is the format for MJPEG streaming
        # The boundary is used to separate different frames in the stream
        # Each frame starts with '--frame' and ends with '\r\n'
        # The Content-Type header specifies the type of data being sent
        # The frame data is sent as a byte stream
        # The '\r\n' at the end indicates the end of the current frame
        # The 'Content-Type: image/jpeg' header indicates that the data is a JPEG image
        # The '\r\n' after the header indicates the end of the headers for this frame
        # The frame data follows, and ends with '\r\n'
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return render_template_string(
        HTML_PAGE,
        threshold=MOTION_AREA_THRESHOLD,
        pause_time=MOTION_PAUSE_TIME,
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
        # Disable auto features for the duration of MOTION_PAUSE_TIME
        MANUAL_OVERRIDE_PAUSE_UNTIL = time.time() + MOTION_PAUSE_TIME
    return ("", 204)  # No content response

@app.route('/tilt_step')
def tilt_step_route():
    global MANUAL_OVERRIDE_PAUSE_UNTIL
    direction = request.args.get('direction')
    fine = request.args.get('fine') == 'true'
    if direction in ["up", "down"]:
        step_servo_tilt(direction, fine)
        # Disable auto features for the duration of MOTION_PAUSE_TIME
        MANUAL_OVERRIDE_PAUSE_UNTIL = time.time() + MOTION_PAUSE_TIME
    return ("", 204)  # No content response


@app.route('/solinoid_pulse')
def solinoid_pulse_route():
    solinoid_pulse()
    return ("", 204)  # No content response

@app.route('/solinoid_auto3')
def solinoid_auto3_route():
    solinoid_auto(3)
    return ("", 204)  # No content response

@app.route('/set_motion_threshold')
def set_motion_threshold():
    global MOTION_AREA_THRESHOLD
    try:
        value = int(request.args.get('value', 5000))
        MOTION_AREA_THRESHOLD = max(50, min(value, 5000))  # Clamp for safety, min 50, max 5000
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_motion_pause')
def set_motion_pause():
    global MOTION_PAUSE_TIME
    try:
        value = float(request.args.get('value', 2.0))
        MOTION_PAUSE_TIME = max(0, min(value, 3))  # Clamp between 0 and 3 seconds
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_pre_move_pause')
def set_pre_move_pause():
    global PRE_MOVE_PAUSE_TIME
    try:
        value = float(request.args.get('value', 0.0))
        PRE_MOVE_PAUSE_TIME = max(0, min(value, 2))  # Clamp between 0 and 2 seconds
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/set_auto_scan_wait')
def set_auto_scan_wait():
    global AUTO_SCAN_WAIT
    try:
        value = int(request.args.get('value', 15))
        AUTO_SCAN_WAIT = max(5, min(value, 60))  # Clamp between 5 and 60 seconds
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
import threading

def auto_scan_thread():
    global PAN_POSITION, AUTO_SCAN_ENABLED, auto_scan_next_time, AUTO_SCAN_WAIT
    scan_direction = -1  # -1 for right, 1 for left
    PAN_STEP = 800  # Pan by +/-800 per move

    while True:
        if AUTO_SCAN_ENABLED:
            # Calculate next position, clamp to limits
            next_pos = PAN_POSITION + (PAN_STEP * scan_direction)
            if scan_direction == -1 and next_pos < PAN_MIN:
                next_pos = PAN_MIN
            elif scan_direction == 1 and next_pos > PAN_MAX:
                next_pos = PAN_MAX

            # Move to next position if needed
            steps = abs(PAN_POSITION - next_pos)
            clockwise = (next_pos > PAN_POSITION)
            if steps > 0:
                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps, clockwise=clockwise)
                PAN_POSITION = next_pos

            auto_scan_next_time = time.time() + AUTO_SCAN_WAIT
            time.sleep(AUTO_SCAN_WAIT)

            # If at edge, reverse direction
            if PAN_POSITION == PAN_MIN or PAN_POSITION == PAN_MAX:
                scan_direction *= -1
        else:
            auto_scan_next_time = time.time() + 1
            time.sleep(1)

# Start the auto scan thread
threading.Thread(target=auto_scan_thread, daemon=True).start()

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # Cleanup GPIO and pigpio on ßexit
        pi.stop()
        picam2.close()
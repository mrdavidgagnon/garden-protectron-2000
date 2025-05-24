from flask import Flask, Response, render_template_string
from picamera2 import Picamera2, Preview
import cv2

import RPi.GPIO as gpio
import pigpio
import time
from flask import Flask, Response, render_template_string, request
from picamera2 import Picamera2, Preview
import cv2

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
DIR_PIN_2 = 22  # Direction pin for Motor 2
STEP_PIN_2 = 23  # Step pin for Motor 2
STEP_DELAY =  0.0001  # Delay between steps in seconds

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
    if direction == "right":
        rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=100, clockwise=False)
    elif direction == "left":
        rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=100, clockwise=True)
def step_servo_tilt(direction, fine=False):
    if direction == "up":
       rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=100, clockwise=True)
    elif direction == "down":
        rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=100, clockwise=False)

# Global variable for motion area threshold (default 5000)
MOTION_AREA_THRESHOLD = 5000

# Calibration: how many pixels in the image correspond to one step of the motor
PIXELS_PER_STEP_PAN = 1   # Adjust experimentally
PIXELS_PER_STEP_TILT = 1  # Adjust experimentally

# Add this global variable for the pause time (in seconds) after centering on motion
MOTION_PAUSE_TIME = 1.0  # Default 1 second

# Add this global variable to enable/disable auto movement
AUTO_MOTION_ENABLED = True

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
            <button class="arrow-right" onclick="fetch('/pan_step?direction=right')">&#8594;</button>
            <button class="arrow-down" onclick="fetch('/tilt_step?direction=down')">&#8595;</button>
        </div>
        <button onclick="fetch('/solinoid_on')">Solenoid ON</button>
        <button onclick="fetch('/solinoid_off')">Solenoid OFF</button>
        <button onclick="fetch('/solinoid_pulse')">Solenoid Pulse</button>
        <button onclick="fetch('/solinoid_auto3')">Solenoid 3</button>
        <button onclick="fetch('/solinoid_auto10')">Solenoid 10</button>
    <div>
        <label for="motion-threshold">Motion Area Threshold: <span id="threshold-value">{{ threshold }}</span></label>
        <input type="range" min="50" max="5000" value="{{ threshold }}" id="motion-threshold" step="100" 
               oninput="document.getElementById('threshold-value').innerText=this.value"
               onchange="fetch('/set_motion_threshold?value='+this.value)">
    </div>
    <div>
        <label for="motion-pause">Pause After Centering (s): <span id="pause-value">{{ pause_time }}</span></label>
        <input type="range" min="0" max="2" value="{{ pause_time }}" id="motion-pause" step="0.1"
               oninput="document.getElementById('pause-value').innerText=this.value"
               onchange="fetch('/set_motion_pause?value='+this.value)">
    </div>
    <div>
        <label for="auto-motion">Auto Movement:</label>
        <button id="auto-motion-btn" onclick="toggleAutoMotion()">{{ 'ON' if auto_motion else 'OFF' }}</button>
    </div>
    </div>
    <script>
    function toggleAutoMotion() {
        fetch('/toggle_auto_motion')
          .then(() => location.reload());
    }
    </script>
    </body>
    </html>
    """


def gen_frames():
    if not hasattr(gen_frames, "move_in_progress"):
        gen_frames.move_in_progress = False
    if not hasattr(gen_frames, "target_motion_box"):
        gen_frames.target_motion_box = None
    if not hasattr(gen_frames, "pause_until"):
        gen_frames.pause_until = 0

    while True:
        frame = picam2.capture_array()
        height, width, _ = frame.shape
        center_x, center_y = width // 2, height // 2

        # superimpose the frame with a 5 px thick green line, 5% down from the top
        line_thickness = 1
        line_y_position = int(height * 0.05)
        cv2.line(frame, (30, line_y_position), (width-30, line_y_position), (0, 255, 0), line_thickness)

        # Draw mil dot crosshairs in the center
        crosshair_length = 40  # length of crosshair lines
        dot_radius = 4         # radius of mil dots
        color = (0, 255, 0)
        thickness = 2

        # Horizontal line
        cv2.line(frame, (center_x - crosshair_length, center_y), (center_x + crosshair_length, center_y), color, thickness)
        # Vertical line
        cv2.line(frame, (center_x, center_y - crosshair_length), (center_x, center_y + crosshair_length), color, thickness)

        # Mil dots: center and at 1/3 and 2/3 of crosshair length from center
        for offset in [0, crosshair_length // 3, 2 * crosshair_length // 3]:
            # Center dot
            if offset == 0:
                cv2.circle(frame, (center_x, center_y), dot_radius, color, -1)
            else:
                # Horizontal dots
                cv2.circle(frame, (center_x - offset, center_y), dot_radius, color, -1)
                cv2.circle(frame, (center_x + offset, center_y), dot_radius, color, -1)
                # Vertical dots
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

        # Convert frame to grayscale for motion detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        now = time.time()
        if not hasattr(gen_frames, "prev_gray"):
            gen_frames.prev_gray = gray
            motion_boxes = []
        else:
            # If a move is in progress or we're in the pause period, skip motion detection and just update prev_gray
            if gen_frames.move_in_progress or now < gen_frames.pause_until:
                gen_frames.prev_gray = gray
            else:
                frame_delta = cv2.absdiff(gen_frames.prev_gray, gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)

                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                motion_boxes = []
                for contour in contours:
                    if cv2.contourArea(contour) < MOTION_AREA_THRESHOLD:
                        continue
                    (x, y, w, h) = cv2.boundingRect(contour)
                    motion_boxes.append((x, y, w, h))
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3)

                # Only perform auto-move if enabled
                if AUTO_MOTION_ENABLED:
                    # If not already tracking a target, pick the largest box as the target
                    if not gen_frames.target_motion_box and motion_boxes:
                        gen_frames.target_motion_box = max(motion_boxes, key=lambda b: b[2]*b[3])

                    # If we have a target, move to center on it and ignore all other motion until done
                    if gen_frames.target_motion_box:
                        gen_frames.move_in_progress = True  # Set flag before moving

                        x, y, w, h = gen_frames.target_motion_box
                        target_x = x + w // 2
                        target_y = y + h // 2

                        offset_x = target_x - center_x
                        offset_y = target_y - center_y

                        steps_pan = int(abs(offset_x) / PIXELS_PER_STEP_PAN)
                        steps_tilt = int(abs(offset_y) / PIXELS_PER_STEP_TILT)

                        # Move pan (left/right)
                        if steps_pan > 0:
                            if offset_x > 0:
                                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=False)
                            else:
                                rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=steps_pan, clockwise=True)

                        # Move tilt (up/down)
                        if steps_tilt > 0:
                            if offset_y > 0:
                                rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=False)
                            else:
                                rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=steps_tilt, clockwise=True)

                        # After moving, clear the target and pause further tracking
                        gen_frames.target_motion_box = None
                        gen_frames.move_in_progress = False
                        gen_frames.pause_until = time.time() + MOTION_PAUSE_TIME

                        # Fire the solenoid 3 times after centering on motion
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
    return render_template_string(HTML_PAGE, threshold=MOTION_AREA_THRESHOLD, pause_time=MOTION_PAUSE_TIME, auto_motion=AUTO_MOTION_ENABLED)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/pan_step')
def pan_step_route():
    direction = request.args.get('direction')
    fine = request.args.get('fine') == 'true'
    if direction in ["left", "right"]:
        step_servo_pan(direction, fine)
    return ("", 204)  # No content response

@app.route('/tilt_step')
def tilt_step_route():
    direction = request.args.get('direction')
    fine = request.args.get('fine') == 'true'
    if direction in ["up", "down"]:
        step_servo_tilt(direction, fine)
        return ("", 204)  # No content response

@app.route('/solinoid_on')
def solinoid_on_route():
    solinoid_on()
    return ("", 204)  # No content response

@app.route('/solinoid_off')
def solinoid_off_route():
    solinoid_off()
    return ("", 204)  # No content response

@app.route('/solinoid_pulse')
def solinoid_pulse_route():
    solinoid_pulse()
    return ("", 204)  # No content response

@app.route('/solinoid_auto3')
def solinoid_auto3_route():
    solinoid_auto(3)
    return ("", 204)  # No content response

@app.route('/solinoid_auto10')
def solinoid_auto10_route():
    solinoid_auto(10)
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
        value = float(request.args.get('value', 1.0))
        MOTION_PAUSE_TIME = max(0, min(value, 2))  # Clamp between 0 and 2 seconds
        return ("", 204)
    except Exception:
        return ("Invalid value", 400)

@app.route('/toggle_auto_motion')
def toggle_auto_motion():
    global AUTO_MOTION_ENABLED
    AUTO_MOTION_ENABLED = not AUTO_MOTION_ENABLED
    return ("", 204)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # Cleanup GPIO and pigpio on exit
        pi.stop()
        picam2.close()

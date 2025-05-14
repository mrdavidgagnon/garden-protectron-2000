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

# Servo setup with pigpio
SERVO_PIN_PAN = 24  # Replace with the GPIO pin connected to your servo
SERVO_PIN_TILT = 23  # Replace with the GPIO pin connected to your servo
GPIO_PWM_FREQUENCY = 50
NEUTRAL_DC = 1500 # 90deg
MIN_DC = 500 # 0deg
MAX_DC = 2500 # 180deg
CURRENT_PAN = NEUTRAL_DC
CURRENT_TILT = NEUTRAL_DC
pi = pigpio.pi()
pi.set_mode(SERVO_PIN_PAN, pigpio.OUTPUT)
pi.set_servo_pulsewidth(SERVO_PIN_PAN, NEUTRAL_DC)
pi.set_mode(SERVO_PIN_TILT, pigpio.OUTPUT)
pi.set_servo_pulsewidth(SERVO_PIN_TILT, NEUTRAL_DC)

# Solinoid setup 
SOLINOID_PIN = 17  # Replace with the GPIO pin connected to your solenoid
SOLINOID_PIN_2 = 27
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

PAN_STEP_FINE = 10
TILT_STEP_FINE = 10
PAN_STEP = 50
TILT_STEP = 50
def step_servo_pan(direction, fine=False):
    global CURRENT_PAN
    step = PAN_STEP_FINE if fine else PAN_STEP
    if direction == "right":
        CURRENT_PAN = max(MIN_DC, CURRENT_PAN - step)
        pi.set_servo_pulsewidth(SERVO_PIN_PAN, CURRENT_PAN)
    elif direction == "left":
        CURRENT_PAN = min(MAX_DC, CURRENT_PAN + step)
        pi.set_servo_pulsewidth(SERVO_PIN_PAN, CURRENT_PAN)
    print(f"Pan position: {CURRENT_PAN}")
def step_servo_tilt(direction, fine=False):
    global CURRENT_TILT
    step = TILT_STEP_FINE if fine else TILT_STEP
    if direction == "up":
        CURRENT_TILT = max(MIN_DC, CURRENT_TILT - step)
        pi.set_servo_pulsewidth(SERVO_PIN_TILT, CURRENT_TILT)
    elif direction == "down":
        CURRENT_TILT = min(MAX_DC, CURRENT_TILT + step)
        pi.set_servo_pulsewidth(SERVO_PIN_TILT, CURRENT_TILT)
    print(f"Tilt position: {CURRENT_TILT}")
        
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
    </div>
    </body>
    </html>
    """



def gen_frames():
    while True:
        frame = picam2.capture_array()


        # superimpose the frame with a 5 px thick green line, 5% down from the top
        height, width, _ = frame.shape
        line_thickness = 1
        line_y_position = int(height * 0.05)
        cv2.line(frame, (30, line_y_position), (width-30, line_y_position), (0, 255, 0), line_thickness)

        # Draw mil dot crosshairs in the center
        center_x, center_y = width // 2, height // 2
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
    return render_template_string(HTML_PAGE)

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

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # Cleanup GPIO and pigpio on exit
        pi.set_servo_pulsewidth(SERVO_PIN_PAN, 0)
        pi.set_servo_pulsewidth(SERVO_PIN_TILT, 0)
        pi.stop()
        picam2.close()        

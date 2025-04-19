from flask import Flask, Response, render_template_string
from picamera2 import Picamera2, Preview
import cv2

import pigpio
import time
from flask import Flask, Response, render_template_string, request
from picamera2 import Picamera2, Preview
import cv2

app = Flask(__name__)

# Initialize Picamera2
picam2 = Picamera2()
camera_config = picam2.create_video_configuration(main={"size": (640, 480)})
picam2.configure(camera_config)
picam2.start()

# Servo setup with pigpio
SERVO_PIN_PAN = 24  # Replace with the GPIO pin connected to your servo
SERVO_PIN_TILT = 23  # Replace with the GPIO pin connected to your servo
GPIO_PWM_FREQUENCY = 50
NEUTRAL_DC = 1500 # 90deg
MIN_DC = 500 # 0deg
MAX_DC = 2500 # 180deg

pi = pigpio.pi()
pi.set_mode(SERVO_PIN_PAN, pigpio.OUTPUT)
pi.set_servo_pulsewidth(SERVO_PIN_PAN, NEUTRAL_DC)
pi.set_mode(SERVO_PIN_TILT, pigpio.OUTPUT)
pi.set_servo_pulsewidth(SERVO_PIN_TILT, NEUTRAL_DC)


def move_servo(direction):
    if direction == "left":
        pi.set_servo_pulsewidth(SERVO_PIN_PAN, MIN_DC)
    elif direction == "right":
        pi.set_servo_pulsewidth(SERVO_PIN_PAN, MAX_DC)
    time.sleep(0.5)
    pi.set_servo_pulsewidth(SERVO_PIN_PAN, NEUTRAL_DC)  # Back to neutral


HTML_PAGE = """
<html>
<head>
<title>Garden Protectron 2000</title>
</head>
<body>
<img src="{{ url_for('video_feed') }}" width="640" height="480">
<br>
<button onclick="fetch('/move_servo?direction=left')">Move Left</button>
<button onclick="fetch('/move_servo?direction=right')">Move Right</button>
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

@app.route('/move_servo')
def move_servo_route():
    direction = request.args.get('direction')
    if direction in ["left", "right"]:
        move_servo(direction)
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
import time
import pigpio

# GPIO pin configuration
DIR_PIN = 20  # Direction pin
STEP_PIN = 21  # Step pin

# Initialize pigpio
pi = pigpio.pi()
if not pi.connected:
    raise RuntimeError("Failed to connect to pigpio daemon")

# Function to initialize the stepper driver
def initialize_stepper():
    pi.set_mode(DIR_PIN, pigpio.OUTPUT)
    pi.set_mode(STEP_PIN, pigpio.OUTPUT)
    
    pi.write(DIR_PIN, 0)  # Set default direction (e.g., clockwise)

# Function to rotate the motor
def rotate_motor(steps, delay, clockwise=True):
    pi.write(DIR_PIN, 1 if clockwise else 0)  # Set direction
    for _ in range(steps):
        pi.write(STEP_PIN, 1)
        time.sleep(delay)
        pi.write(STEP_PIN, 0)
        time.sleep(delay)

# Main demo
if __name__ == "__main__":
    try:
        initialize_stepper()
        print("Stepper motor demo starting...")
        
        # Rotate clockwise
        print("Rotating clockwise...")
        rotate_motor(steps=1000, delay=0.0001, clockwise=True)
        
        # Pause
        time.sleep(1)
        
        # Rotate counterclockwise
        print("Rotating counterclockwise...")
        rotate_motor(steps=1000, delay=0.0001, clockwise=False)
        
        print("Demo complete.")
    except KeyboardInterrupt:
        print("Demo interrupted.")
    finally:
        pi.stop()  # Disconnect from pigpio
        print("Stepper motor disabled.")
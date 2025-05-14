import time
import pigpio

# GPIO pin configuration for Motor 1
DIR_PIN_1 = 20  # Direction pin for Motor 1
STEP_PIN_1 = 21  # Step pin for Motor 1

# GPIO pin configuration for Motor 2
DIR_PIN_2 = 22  # Direction pin for Motor 2
STEP_PIN_2 = 23  # Step pin for Motor 2

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
def rotate_motor(dir_pin, step_pin, steps, delay, clockwise=True):
    pi.write(dir_pin, 1 if clockwise else 0)  # Set direction
    for _ in range(steps):
        pi.write(step_pin, 1)
        time.sleep(delay)
        pi.write(step_pin, 0)
        time.sleep(delay)

# Main demo
if __name__ == "__main__":
    try:
        initialize_steppers()
        print("Stepper motor demo starting...")
        
        # Rotate Motor 1 clockwise
        print("Rotating Motor 1 clockwise...")
        rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=1000, delay=0.00005, clockwise=True)
        
        # Pause
        time.sleep(1)
        
        # Rotate Motor 1 counterclockwise
        print("Rotating Motor 1 counterclockwise...")
        rotate_motor(DIR_PIN_1, STEP_PIN_1, steps=1000, delay=0.00005, clockwise=False)
        
        # Pause
        time.sleep(1)
        
        # Rotate Motor 2 clockwise
        print("Rotating Motor 2 clockwise...")
        rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=1000, delay=0.00005, clockwise=True)
        
        # Pause
        time.sleep(1)
        
        # Rotate Motor 2 counterclockwise
        print("Rotating Motor 2 counterclockwise...")
        rotate_motor(DIR_PIN_2, STEP_PIN_2, steps=1000, delay=0.00005, clockwise=False)
        
        print("Demo complete.")
    except KeyboardInterrupt:
        print("Demo interrupted.")
    finally:
        pi.stop()  # Disconnect from pigpio
        print("Stepper motors disabled.")
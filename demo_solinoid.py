import RPi.GPIO as gpio
import time


# Solinoid setup 
SOLINOID_PIN = 26  # Replace with the GPIO pin connected to your solenoid
SOLINOID_PIN_2 = 27


# Initialize GPIO
gpio.setmode(gpio.BCM)
gpio.setup(SOLINOID_PIN, gpio.OUT)
gpio.setup(SOLINOID_PIN_2, gpio.OUT)

# Set the solenoid to LOW (off)
gpio.output(SOLINOID_PIN, gpio.LOW)  # Set the solenoid to LOW (off)    
gpio.output(SOLINOID_PIN_2, gpio.LOW)  # Set the solenoid to LOW (off)   

SOLINOID_PULSE_TIME = 5  # Time in seconds to set the solenoid

def solinoid_on():
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.HIGH)
    time.sleep(SOLINOID_PULSE_TIME)
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)

def solinoid_off():
    gpio.output(SOLINOID_PIN, gpio.HIGH)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)
    time.sleep(SOLINOID_PULSE_TIME)
    time.sleep(SOLINOID_PULSE_TIME)
    gpio.output(SOLINOID_PIN, gpio.LOW)
    gpio.output(SOLINOID_PIN_2, gpio.LOW)

# Test the solenoid
try:
    print("Activating solenoid...")
    solinoid_on()
    time.sleep(2)
    print("Deactivating solenoid...")
    solinoid_off()
except KeyboardInterrupt:
    print("Program interrupted.")
finally:
    gpio.cleanup()
    print("GPIO cleaned up.")      
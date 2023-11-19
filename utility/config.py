# config.py

NODE = 0x45

# Storage settings
STORE_LOCAL = False
STORE_DRIVE = False

# I2C Sensor Addresses
AHT21_ADDRESS = 0x38
#CO2_ADDRESS = 0x52 # Uncomment if the CO2 Addr pin is grounded
CO2_ADDRESS = 0x53
RGB_ADDRESS = 0x29
MLX_ADDRESS = 0x5A
LTR_ADDRESS = 0x53

# Sensor Settings
CO2_ATTEMPTS = 5 # max attempts before giving up on reading CO2 sensor
RGB_LED_PIN = 26 # LED pin of RGB sensor for controlling power to it
NUM_READINGS = 10 # number of data points to collect per sensor attribute
TIME_BETWEEN_READINGS = 0.1 # time between individual sensor readings

LCD_DISPLAY_TIME = 3 # how long each data set is displayed on the LCD before writing next


# SSH/SCP copy settings
SCP_COPY = False
USERNAME = "admin"
IP_ADDRESS = "10.42.0.1"
DESTINATION_COPY_PATH = "home/admin/Desktop/SmartCrop/Images/"


# Server Settings
SERVER_IP_ADDRESS = "10.42.0.1"
SERVER_PORT = 65432

# Image/Camera settings
IMAGE_DIMENSIONS = (1920,1080)
IMAGE_FORMAT = "png"
USE_TIMESTAMP_AS_NAME = True
IMAGE_STORE_PATH = "/home/tarleton/Desktop/SmartCrop/PiZero2W-Async/Images/"

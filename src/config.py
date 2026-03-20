import os
from dotenv import load_dotenv

load_dotenv()

BHAPTICS_APP_ID = os.getenv("BHAPTICS_APP_ID")
BHAPTICS_API_KEY = os.getenv("BHAPTICS_API_KEY")
BHAPTICS_APP_NAME = os.getenv("BHAPTICS_APP_NAME")

MQTT_ADDRESS = os.getenv("MQTT_ADDRESS", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

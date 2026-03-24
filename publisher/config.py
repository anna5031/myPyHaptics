import os
from dotenv import load_dotenv

load_dotenv()

MQTT_ADDRESS = os.getenv("MQTT_ADDRESS", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

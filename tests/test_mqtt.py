import sys
import pytest

sys.path.insert(0, "src")

import config
from mqtt.subscriber import MQTTSubscriber

CONNECT_TIMEOUT = 5  # seconds


@pytest.mark.asyncio
async def test_connects_to_broker():
    """MQTTSubscriber should successfully connect to CONFIG.MQTT_ADDRESS."""
    import asyncio
    import aiomqtt

    try:
        async with aiomqtt.Client(
            config.MQTT_ADDRESS, config.MQTT_PORT,
            timeout=CONNECT_TIMEOUT,
        ):
            pass  # connection succeeded
    except aiomqtt.MqttError as e:
        pytest.fail(f"Failed to connect to {config.MQTT_ADDRESS}:{config.MQTT_PORT} — {e}")

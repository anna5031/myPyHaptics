import asyncio

from mqtt.handler import CommandHandler
from mqtt.subscriber import MQTTSubscriber
from bhaptics.bridge import BHapticsBridge
from bhaptics.service import BHapticsService


async def main():
    sub = MQTTSubscriber()
    
    bridge = BHapticsBridge()
    await bridge.connect()
    haptics_service = BHapticsService(bridge)
    
    handler = CommandHandler(haptics_service)
    sub.subscribe(CommandHandler.TOPIC, handler.handle)
    
    try:
        await sub.connect()
        await sub.listen()
    finally:
        await sub.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

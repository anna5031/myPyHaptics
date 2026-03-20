import asyncio

from mqtt import topic
from mqtt.handler import CommandHandler
from mqtt.subscriber import MQTTSubscriber


async def main():
    sub = MQTTSubscriber()
    handler = CommandHandler()
    sub.subscribe(topic.COMMAND, handler.handle)
    
    try:
        await sub.connect()
        await sub.listen()
    finally:
        await sub.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

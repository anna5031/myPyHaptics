import asyncio

from mqtt import topic
from mqtt.handler import CommandHandler
from mqtt.subscriber import MQTTSubscriber


async def main():
    sub = MQTTSubscriber()
    handler = CommandHandler()
    sub.subscribe(topic.COMMAND, handler.handle)

    await sub.run()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from mqtt.subscriber import MQTTSubscriber


async def main():
    sub = MQTTSubscriber()

    # Register topics and handlers here, e.g.:
    # sub.subscribe("/haptics/vest", on_vest_message)

    await sub.run()


if __name__ == "__main__":
    asyncio.run(main())

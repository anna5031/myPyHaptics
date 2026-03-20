import asyncio
from collections import defaultdict
from typing import Callable, Coroutine, Any

import aiomqtt
import config

Handler = Callable[[str], Coroutine[Any, Any, None]]


class MQTTSubscriber:
    def __init__(self, address: str = config.MQTT_ADDRESS, port: int = config.MQTT_PORT):
        self._address = address
        self._port = port
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler):
        """Register a topic with an async handler."""
        self._handlers[topic].append(handler)

    async def run(self):
        """Connect and listen for messages. Run this in your async main."""
        async with aiomqtt.Client(self._address, self._port) as client:
            for topic in self._handlers:
                await client.subscribe(topic)
                print(f"[MQTT] Subscribed → {topic}")
            print(f"[MQTT] Connected to {self._address}:{self._port}")

            async for message in client.messages:
                topic = str(message.topic)
                payload = message.payload.decode("utf-8", errors="replace")
                print(f"[MQTT] {topic}: {payload}")
                await self._dispatch(topic, payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _dispatch(self, topic: str, payload: str):
        handlers = self._handlers.get(topic, [])
        await asyncio.gather(*(h(payload) for h in handlers))

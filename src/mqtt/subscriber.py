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
        self._client: aiomqtt.Client | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler):
        """Register a topic with an async handler."""
        self._handlers[topic].append(handler)

    async def connect(self):
        """Connect to the broker and subscribe to all registered topics."""
        self._client = aiomqtt.Client(self._address, self._port)
        await self._client.__aenter__()
        for topic in self._handlers:
            await self._client.subscribe(topic)
            print(f"[MQTT] Subscribed → {topic}")
        print(f"[MQTT] Connected to {self._address}:{self._port}")

    async def listen(self):
        """Listen for messages indefinitely. Call connect() first."""
        assert self._client is not None, "Call connect() before listen()"
        async for message in self._client.messages:
            topic = str(message.topic)
            payload = message.payload.decode("utf-8", errors="replace")
            print(f"[MQTT] {topic}: {payload}")
            
            handlers = self._handlers.get(topic, [])
            for h in handlers:
                asyncio.create_task(h(payload))

    async def disconnect(self):
        """Disconnect from the broker."""
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None
            print("[MQTT] Disconnected")

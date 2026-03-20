import asyncio
import pytest
from src.mqtt.subscriber import MQTTSubscriber

class DummyMessage:
    def __init__(self, topic, payload):
        class Topic:
            def __str__(self): return topic
        self.topic = Topic()
        self.payload = payload.encode("utf-8")

class _AsyncMessageGen:
    def __init__(self, msgs):
        self.msgs = msgs
    async def __aiter__(self):
        for m in self.msgs:
            yield m

class DummyClient:
    def __init__(self, messages):
        self.messages = _AsyncMessageGen(messages)

@pytest.mark.asyncio
async def test_subscriber_async_execution():
    """Asserts that the subscriber runs multiple messages concurrently (fire-and-forget)."""
    sub = MQTTSubscriber()
    
    # Inject our mock MQTT client
    sub._client = DummyClient([
        DummyMessage("sensor/data", "msg1"),
        DummyMessage("sensor/data", "msg2")
    ])

    events = []
    
    async def slow_handler(payload):
        events.append(f"start {payload}")
        # The sleep simulates I/O (e.g., db lookup or API request).
        # We use a tiny sleep so the test flies.
        await asyncio.sleep(0.1)
        events.append(f"end {payload}")

    sub.subscribe("sensor/data", slow_handler)

    # Run the loop. Our dummy client will instantly blast out its 2 messages
    # and then the generator ends, terminating the listen loop naturally!
    await sub.listen()

    # The loop processed both messages but the handlers are running in the background!
    # Let's wait slightly longer than our artificial 0.1s I/O delay so the background
    # tasks can complete.
    await asyncio.sleep(0.2)

    # IF SEQUENTIAL: 
    # start msg1 -> end msg1 -> start msg2 -> end msg2
    
    # IF CONCURRENT (what we expect):
    # start msg1 -> start msg2 -> end msg1 -> end msg2
    assert events == [
        "start msg1",
        "start msg2",
        "end msg1",
        "end msg2"
    ], f"Execution was NOT fully concurrent! History: {events}"

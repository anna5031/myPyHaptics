import sys
import json
import pytest

sys.path.insert(0, "src")

from mqtt.handler import CommandHandler
from mqtt.message import StartMessage, StopMessage


class RecordingHandler(CommandHandler):
    """Subclass that records which methods were called."""

    def __init__(self):
        self.started: StartMessage | None = None
        self.stopped: bool = False

    async def _on_start(self, msg: StartMessage):
        self.started = msg

    async def _on_stop(self, msg: StopMessage):
        self.stopped = True


@pytest.fixture
def handler():
    return RecordingHandler()


@pytest.mark.asyncio
async def test_on_start_called(handler):
    payload = json.dumps({"command": "start", "bpm": 60, "time": 1000})
    await handler.handle(payload)

    assert handler.started is not None
    assert handler.started.bpm == 60
    assert handler.started.time == 1000


@pytest.mark.asyncio
async def test_on_stop_called(handler):
    payload = json.dumps({"command": "stop"})
    await handler.handle(payload)

    assert handler.stopped is True


@pytest.mark.asyncio
async def test_unknown_command_does_not_raise(handler, capsys):
    payload = json.dumps({"command": "unknown"})
    await handler.handle(payload)

    assert "unknown" in capsys.readouterr().out

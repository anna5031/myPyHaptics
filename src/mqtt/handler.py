import json
from datetime import datetime

from mqtt.message import StartMessage, StopMessage
from utils.scheduler import Scheduler


class CommandHandler:
    TOPIC = "bHaptics/command"

    def __init__(self):
        self.scheduler = Scheduler()

    async def handle(self, payload: str):
        command = json.loads(payload).get("command")
        if command == "start":
            await self._on_start(StartMessage(payload))
        elif command == "stop":
            await self._on_stop(StopMessage(payload))
        else:
            print(f"[CommandHandler] Unknown command: {command!r}")

    async def _on_start(self, msg: StartMessage):
        def callback():
            print(f"[CommandHandler] Executed scheduled start for bpm={msg.bpm} at time={msg.time}!")

        # Convert the float timestamp back to a datetime to satisfy the new typed signature
        target_dt = datetime.fromtimestamp(msg.time)

        self.scheduler.schedule(
            target_dt,
            callback
        )

    async def _on_stop(self, msg: StopMessage):
        print("[CommandHandler] Stop")

import json

from mqtt.message import StartMessage, StopMessage


class CommandHandler:
    async def handle(self, payload: str):
        command = json.loads(payload).get("command")
        if command == "start":
            await self._on_start(StartMessage(payload))
        elif command == "stop":
            await self._on_stop(StopMessage(payload))
        else:
            print(f"[CommandHandler] Unknown command: {command!r}")

    async def _on_start(self, msg: StartMessage):
        print(f"[CommandHandler] Start — bpm={msg.bpm}, time={msg.time}")

    async def _on_stop(self, msg: StopMessage):
        print("[CommandHandler] Stop")

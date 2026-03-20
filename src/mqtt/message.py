import json


class StartMessage:
    def __init__(self, payload: str):
        data = json.loads(payload)
        self.bpm: int = data["bpm"]
        self.time: int = data["time"]  # UTC timestamp in milliseconds


class StopMessage:
    def __init__(self, payload: str):
        pass  # no fields


type Message = StartMessage | StopMessage

_REGISTRY = {
    "start": StartMessage,
    "stop": StopMessage,
}


def parse(payload: str) -> Message:
    command = json.loads(payload).get("command")
    cls = _REGISTRY.get(command)
    if cls is None:
        raise ValueError(f"Unknown command: {command!r}")
    return cls(payload)

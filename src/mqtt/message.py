import json


class StartMessage:
    def __init__(self, payload: str):
        data = json.loads(payload)
        self.bpm: int = data["bpm"]
        self.time: float = data["time"]  # Float timestamp in seconds (from time.time())


class StopMessage:
    def __init__(self, payload: str):
        pass  # no fields


type Message = StartMessage | StopMessage

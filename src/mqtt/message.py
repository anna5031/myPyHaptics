import json


class PlayDotMessage:
    def __init__(self, payload: str):
        data = json.loads(payload)
        self.time: int = data["time"]  # UTC timestamp in milliseconds

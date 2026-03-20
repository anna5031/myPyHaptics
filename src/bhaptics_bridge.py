import bhaptics_python
import asyncio

TACT_SUIT = 0
MOTORS_COUNT = 32

class BHapticsBridge:
    def __init__(self, app_id="698945534e2e268ff3a49d5b", api_key="BnlVMoYwk8ikSahocPx5", app_name="Make Lab"):
        self.app_id = app_id
        self.api_key = api_key
        self.app_name = app_name

    async def connect(self):
        result = await bhaptics_python.registry_and_initialize(self.app_id, self.api_key, self.app_name)
        return result

    async def play_dot(self, strength):
        device_type = TACT_SUIT
        motors_count = MOTORS_COUNT
        await bhaptics_python.play_dot(device_type, strength, [strength] * motors_count)


if __name__ == "__main__":
    bridge = BHapticsBridge()
    result = asyncio.run(bridge.connect())
    asyncio.run(bridge.play_dot(100))
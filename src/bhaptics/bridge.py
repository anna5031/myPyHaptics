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

    async def play_loop(self, strength, bpm):
        interval = int(60000 / bpm) 
        intensity = min(10.0, float(strength) / 10.0)
        
        # event_name, intensity, duration_multiplier, x_offset, y_offset, interval(ms), max_count
        # duration multiplier set to 1.0 to prevent the metronome beat from stretching and overlapping
        await bhaptics_python.play_loop("bass", intensity, 0.1, 0, 0, interval, 100000000)
        # await asyncio.sleep(10000)  # Keep the loop running for a while to demonstrate the metronome
    
    async def stop_metronome(self):
        await bhaptics_python.stop_all()

async def main():
    bridge = BHapticsBridge()
    result = await bridge.connect()
    print("connection: ", result)
    print("Starting metronome...")
    await bridge.play_loop(100, 90)

if __name__ == "__main__":
    asyncio.run(main())
    while True:
        print("DOne!!")
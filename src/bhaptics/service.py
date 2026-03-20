from bhaptics_bridge import BHapticsBridge
import asyncio

is_running = False

class BHapticsService:
    def __init__(self, bridge: BHapticsBridge):
        self.bridge = bridge

    async def start_metronome(self, bpm: int):
        await self.bridge.play_loop(100, bpm)

    async def stop_metronome(self):
        

async def main():
    bridge = BHapticsBridge()
    await bridge.connect()
    service = BHapticsService(bridge)
    print("Starting metronome...")
    await service.start_metronome(120)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Metronome stopped.")
import atexit
import asyncio
import concurrent.futures
import threading
import time

import bhaptics_python
from flask import Flask, jsonify, request


APP_ID = "698945534e2e268ff3a49d5b"
API_KEY = "BnlVMoYwk8ikSahocPx5"
APP_NAME = "Hello, bHaptics!"
MOTOR_LEN = 32

app = Flask(__name__)


class HapticController:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.initialized = False
        self.pattern_task: asyncio.Task | None = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _initialize(self) -> None:
        if self.initialized:
            return

        result = await bhaptics_python.registry_and_initialize(APP_ID, API_KEY, APP_NAME)
        print(f"Initialization result: {result}")
        self.initialized = True

    async def _play_loop(self, bpm: int) -> None:
        beat_interval = 60.0 / bpm
        next_tick = time.perf_counter()

        while True:
            values = [10] * MOTOR_LEN
            await bhaptics_python.play_dot(0, 100, values, -1)

            next_tick += beat_interval
            now = time.perf_counter()
            sleep_time = next_tick - now

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                while next_tick <= now:
                    next_tick += beat_interval

    async def _cancel_pattern_task(self) -> None:
        if not self.pattern_task or self.pattern_task.done():
            return

        self.pattern_task.cancel()
        try:
            await self.pattern_task
        except asyncio.CancelledError:
            pass

    async def _set_bpm_async(self, bpm: int) -> None:
        if bpm <= 0:
            raise ValueError("bpm must be a positive integer")

        await self._initialize()
        await self._cancel_pattern_task()
        self.pattern_task = self.loop.create_task(self._play_loop(bpm))

    async def _stop_async(self) -> None:
        await self._cancel_pattern_task()
        if self.initialized:
            await bhaptics_python.stop_all()

    async def _close_async(self) -> None:
        await self._stop_async()
        if self.initialized:
            await bhaptics_python.close()
            self.initialized = False

    def set_bpm(self, bpm: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._set_bpm_async(bpm), self.loop)
        future.result(timeout=timeout)

    def stop(self, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._stop_async(), self.loop)
        future.result(timeout=timeout)

    def close(self) -> None:
        if not self.loop.is_running():
            return

        try:
            future = asyncio.run_coroutine_threadsafe(self._close_async(), self.loop)
            future.result(timeout=5.0)
        except Exception:
            pass
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2.0)


controller = HapticController()
atexit.register(controller.close)


def _extract_bpm() -> int:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if "bpm" in payload:
            return int(payload["bpm"])

    form_bpm = request.form.get("bpm")
    if form_bpm is not None:
        return int(form_bpm)

    query_bpm = request.args.get("bpm")
    if query_bpm is not None:
        return int(query_bpm)

    raw_body = request.get_data(as_text=True).strip()
    if raw_body:
        return int(raw_body)

    raise ValueError("missing bpm")


@app.post("/bpm")
def set_bpm_route():
    try:
        bpm = _extract_bpm()
        controller.set_bpm(bpm)
        return jsonify({"status": "ok", "bpm": bpm}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "send a positive integer bpm"}), 400
    except concurrent.futures.TimeoutError:
        return jsonify({"status": "error", "message": "timeout while starting haptic loop"}), 504
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/stop")
def stop_route():
    try:
        controller.stop()
        return jsonify({"status": "stopped"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


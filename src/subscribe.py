from __future__ import annotations

import argparse
import asyncio
import os
import signal
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

try:
    import bhaptics_python
except ModuleNotFoundError as exc:
    bhaptics_python = None
    _BHAPTICS_IMPORT_ERROR = exc
else:
    _BHAPTICS_IMPORT_ERROR = None

SUBSCRIBER_ID = 1

TOPIC_BPM = "bhaptics/bpm"
TOPIC_RUN = "bhaptics/run"

ENV_FILE = ".env"
ENV_APP_ID = "BHAPTICS_APP_ID"
ENV_API_KEY = "BHAPTICS_API_KEY"
ENV_APP_NAME = "BHAPTICS_APP_NAME"
DEFAULT_APP_NAME = "Hello, bHaptics!"
MOTOR_LEN = 32
DEFAULT_BPM = 120


@dataclass(frozen=True)
class BrokerConfig:
    host: str
    port: int
    keepalive: int
    qos: int
    username: str | None
    password: str | None


def _load_dotenv(path: str = ENV_FILE) -> None:
    try:
        with open(path, encoding="utf-8") as file:
            lines = file.readlines()
    except FileNotFoundError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _get_bhaptics_credentials() -> tuple[str, str, str]:
    _load_dotenv()
    app_id = os.getenv(ENV_APP_ID, "").strip()
    api_key = os.getenv(ENV_API_KEY, "").strip()
    app_name = os.getenv(ENV_APP_NAME, DEFAULT_APP_NAME).strip() or DEFAULT_APP_NAME

    missing: list[str] = []
    if not app_id:
        missing.append(ENV_APP_ID)
    if not api_key:
        missing.append(ENV_API_KEY)
    if missing:
        missing_vars = ", ".join(missing)
        raise ValueError(
            f"missing required credentials: {missing_vars}. "
            f"set them in environment variables or {ENV_FILE}"
        )

    return app_id, api_key, app_name


def _parse_broker(value: str, fallback_port: int) -> tuple[str, int]:
    raw = value.strip()
    if not raw:
        raise ValueError("broker must not be empty")

    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname
        port = parsed.port or fallback_port
    else:
        parsed = urlparse(f"mqtt://{raw}")
        host = parsed.hostname
        port = parsed.port or fallback_port

    if not host:
        raise ValueError(f"invalid broker value: {value!r}")

    return host, port


def _parse_run_payload(payload: str) -> int:
    normalized = payload.strip().lower()
    if normalized in {"1", "true", "on", "start", "yes"}:
        return 1
    if normalized in {"0", "false", "off", "stop", "no"}:
        return 0
    raise ValueError(f"invalid run payload: {payload!r}")


class HapticsController:
    def __init__(self, app_id: str, api_key: str, app_name: str) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.app_name = app_name

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.initialized = False
        self.current_bpm = DEFAULT_BPM
        self.current_run = 0
        self.play_task: asyncio.Task[None] | None = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _initialize(self) -> None:
        if self.initialized:
            return
        result = await bhaptics_python.registry_and_initialize(
            self.app_id,
            self.api_key,
            self.app_name,
        )
        print(f"bHaptics initialization result: {result}")
        self.initialized = True

    async def _play_loop(self) -> None:
        next_tick = time.perf_counter()
        while True:
            bpm = self.current_bpm
            beat_interval = 60.0 / bpm
            values = [10] * MOTOR_LEN
            await bhaptics_python.play_dot(0, 100, values, -1)
            print("played haptic feedback")

            next_tick += beat_interval
            now = time.perf_counter()
            sleep_time = next_tick - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                while next_tick <= now:
                    next_tick += beat_interval

    async def _cancel_play_task(self) -> None:
        if not self.play_task or self.play_task.done():
            self.play_task = None
            return
        self.play_task.cancel()
        try:
            await self.play_task
        except asyncio.CancelledError:
            pass
        self.play_task = None

    async def _set_bpm_async(self, bpm: int) -> None:
        if bpm <= 0:
            raise ValueError("bpm must be a positive integer")
        self.current_bpm = bpm
        print(f"updated bpm={bpm}")

    async def _set_run_async(self, run: int) -> None:
        self.current_run = run
        print(f"updated run={run}")
        await self._initialize()

        if run == 1:
            if self.play_task is None or self.play_task.done():
                self.play_task = self.loop.create_task(self._play_loop())
                print("play loop started")
            return

        await self._cancel_play_task()
        if self.initialized:
            await bhaptics_python.stop_all()
            print("play loop stopped")

    async def _close_async(self) -> None:
        await self._cancel_play_task()
        if self.initialized:
            await bhaptics_python.stop_all()
            await bhaptics_python.close()
            self.initialized = False

    def set_bpm(self, bpm: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._set_bpm_async(bpm), self.loop)
        future.result(timeout=timeout)

    def set_run(self, run: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._set_run_async(run), self.loop)
        future.result(timeout=timeout)

    def close(self) -> None:
        if not self.loop.is_running():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._close_async(), self.loop)
            future.result(timeout=5.0)
        except Exception as exc:
            print(f"warning: failed to cleanly close haptics controller: {exc}")
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2.0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Subscribe MQTT topics and control bHaptics playback."
    )
    parser.add_argument(
        "--broker",
        default="mqtt.makinteract.com",
        help="MQTT broker host or URL (default: mqtt.makinteract.com)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=1883,
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--keepalive",
        type=int,
        default=60,
        help="MQTT keepalive in seconds (default: 60)",
    )
    parser.add_argument(
        "--qos",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="MQTT QoS level for subscription (default: 1)",
    )
    parser.add_argument("--username", default=None, help="MQTT username")
    parser.add_argument("--password", default=None, help="MQTT password")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if bhaptics_python is None:
        print(f"error: missing dependency 'bhaptics_python' ({_BHAPTICS_IMPORT_ERROR})")
        return 1
    try:
        app_id, api_key, app_name = _get_bhaptics_credentials()
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    host, port = _parse_broker(args.broker, args.port)
    config = BrokerConfig(
        host=host,
        port=port,
        keepalive=args.keepalive,
        qos=args.qos,
        username=args.username,
        password=args.password,
    )

    controller = HapticsController(app_id, api_key, app_name)
    stop_event = threading.Event()
    connect_event = threading.Event()
    connect_error: list[str] = []

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.username:
        client.username_pw_set(config.username, config.password)

    def on_connect(
        _client: mqtt.Client,
        _userdata: object,
        _flags: dict[str, int],
        reason_code: object,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        is_failure = getattr(reason_code, "is_failure", None)
        failed = bool(is_failure) if isinstance(is_failure, bool) else False
        if not failed and reason_code == 0:
            _client.subscribe([(TOPIC_BPM, config.qos), (TOPIC_RUN, config.qos)])
            print(f"subscribed to {TOPIC_BPM}, {TOPIC_RUN}")
            connect_event.set()
            return

        if not failed and str(reason_code).strip().lower() in {"success", "0"}:
            _client.subscribe([(TOPIC_BPM, config.qos), (TOPIC_RUN, config.qos)])
            print(f"subscribed to {TOPIC_BPM}, {TOPIC_RUN}")
            connect_event.set()
            return

        connect_error.append(f"MQTT connect failed: {reason_code}")
        connect_event.set()

    def on_message(
        _client: mqtt.Client,
        _userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        payload = msg.payload.decode("utf-8", errors="ignore").strip()
        try:
            if msg.topic == TOPIC_BPM:
                bpm = int(payload)
                controller.set_bpm(bpm)
                return

            if msg.topic == TOPIC_RUN:
                run = _parse_run_payload(payload)
                controller.set_run(run)
                return

            print(f"ignored unknown topic: {msg.topic}")
        except ValueError as exc:
            print(f"ignored invalid payload for {msg.topic}: {payload!r} ({exc})")
        except FutureTimeoutError:
            print(f"timeout applying message for {msg.topic}")
        except Exception as exc:
            print(f"failed handling message for {msg.topic}: {exc}")

    def on_disconnect(
        _client: mqtt.Client,
        _userdata: object,
        _disconnect_flags: object,
        reason_code: object,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if stop_event.is_set():
            return
        print(f"disconnected from broker: {reason_code}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    def _stop_handler(_signum: int, _frame: object) -> None:
        stop_event.set()
        client.disconnect()

    signal.signal(signal.SIGINT, _stop_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop_handler)

    try:
        print(f"connecting to MQTT broker {config.host}:{config.port}")
        client.connect(config.host, config.port, config.keepalive)
        client.loop_start()

        if not connect_event.wait(timeout=5):
            print("error: timeout waiting for MQTT connection")
            return 1
        if connect_error:
            print(f"error: {connect_error[0]}")
            return 1

        print("subscriber running. press Ctrl+C to stop.")
        while not stop_event.is_set():
            time.sleep(0.2)
        return 0
    finally:
        client.loop_stop()
        client.disconnect()
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())

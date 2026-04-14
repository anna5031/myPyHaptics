from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    tk = None
    messagebox = None

SUBSCRIBER_ID = 1
TOPIC_BPM = "bhaptics/bpm"
TOPIC_RUN = "bhaptics/run"
ENV_FILE = ".env"
ENV_MQTT_BROKER = "MQTT_BROKER"
ENV_MQTT_PORT = "MQTT_PORT"
ENV_MQTT_KEEPALIVE = "MQTT_KEEPALIVE"
ENV_MQTT_QOS = "MQTT_QOS"
ENV_MQTT_USERNAME = "MQTT_USERNAME"
ENV_MQTT_PASSWORD = "MQTT_PASSWORD"
DEFAULT_BROKER = "mqtt-web.makinteract.com"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BPM = 120
MIN_EPOCH_MS = 10**11
STALE_START_THRESHOLD_MS = 5000


def _load_dotenv(path: str = ENV_FILE) -> None:
    user_path = Path(path)
    candidates = [user_path]
    if not user_path.is_absolute():
        candidates.append(PROJECT_ROOT / user_path)

    lines: list[str] | None = None
    seen_paths: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not candidate.is_file():
            continue
        with open(candidate, encoding="utf-8-sig") as file:
            lines = file.readlines()
        break

    if lines is None:
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


def _get_env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _get_mqtt_defaults() -> dict[str, str | int | None]:
    _load_dotenv()
    broker = os.getenv(ENV_MQTT_BROKER, DEFAULT_BROKER).strip() or DEFAULT_BROKER
    port = _get_env_int(ENV_MQTT_PORT, 1883, minimum=1)
    keepalive = _get_env_int(ENV_MQTT_KEEPALIVE, 60, minimum=1)
    qos = _get_env_int(ENV_MQTT_QOS, 1, minimum=0)
    if qos not in {0, 1, 2}:
        qos = 1

    username = os.getenv(ENV_MQTT_USERNAME, "").strip() or None
    password = os.getenv(ENV_MQTT_PASSWORD, "").strip() or None

    return {
        "broker": broker,
        "port": port,
        "keepalive": keepalive,
        "qos": qos,
        "username": username,
        "password": password,
    }


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


def _parse_run_payload(payload: str) -> tuple[str, int | None]:
    normalized = payload.strip().lower()
    if normalized in {"0", "false", "off", "stop", "no"}:
        return "stop", None

    try:
        publish_ms = int(payload.strip())
    except ValueError as exc:
        raise ValueError(f"invalid run payload: {payload!r}") from exc

    if publish_ms < MIN_EPOCH_MS:
        raise ValueError(f"invalid start timestamp (expected epoch-ms): {publish_ms}")
    return "start", publish_ms


class CircleOneGui:
    def __init__(self) -> None:
        self._queue: Queue[int] = Queue()
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        if tk is None:
            self._ready.set()
            return

        try:
            root = tk.Tk()
        except Exception:
            self._ready.set()
            return

        root.title("Circle One Timing Test")
        root.resizable(False, False)
        canvas = tk.Canvas(root, width=260, height=180, bg="#111111", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        circle = canvas.create_oval(80, 40, 180, 140, fill="#3a3a3a", outline="#777777", width=3)
        active_until_ms = 0

        def _reset_circle() -> None:
            canvas.itemconfigure(circle, fill="#3a3a3a", outline="#777777")

        def _poll() -> None:
            nonlocal active_until_ms
            if self._closed.is_set():
                try:
                    root.destroy()
                except Exception:
                    pass
                return

            now_ms = int(time.time() * 1000)
            while True:
                try:
                    epoch_ms = self._queue.get_nowait()
                except Empty:
                    break
                active_until_ms = max(active_until_ms, now_ms + 120)
                canvas.itemconfigure(circle, fill="#00d18f", outline="#9fe8cf")
                print(f"circle 1 shown at epoch_ms={epoch_ms} actual_ms={now_ms} delta_ms={now_ms - epoch_ms}")

            if active_until_ms and now_ms >= active_until_ms:
                active_until_ms = 0
                _reset_circle()

            root.after(10, _poll)

        self._ready.set()
        root.after(10, _poll)
        try:
            root.mainloop()
        finally:
            self._closed.set()

    def flash(self, epoch_ms: int) -> None:
        if self._closed.is_set():
            return
        self._queue.put(epoch_ms)

    def close(self) -> None:
        self._closed.set()


class TimingController:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self._status_lock = threading.Lock()
        self.current_bpm = DEFAULT_BPM
        self.current_run = 0
        self.current_run_state = "stopped"
        self.last_payload_target_ms: int | None = None
        self.last_target_ms: int | None = None
        self.last_actual_ms: int | None = None
        self.last_event = "ready"
        self.play_task: asyncio.Task[None] | None = None
        self.scheduled_start_task: asyncio.Task[None] | None = None
        self.current_schedule_id = 0
        self.gui = CircleOneGui() if tk is not None else None
        self.thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _set_run_state(self, state: str) -> None:
        with self._status_lock:
            self.current_run_state = state

    def _set_last_event(self, message: str) -> None:
        with self._status_lock:
            self.last_event = message

    def _set_schedule_times(self, payload_target_ms: int, target_ms: int, actual_ms: int | None) -> None:
        with self._status_lock:
            self.last_payload_target_ms = payload_target_ms
            self.last_target_ms = target_ms
            self.last_actual_ms = actual_ms

    async def _initialize(self) -> None:
        return

    async def _play_loop(self) -> None:
        next_tick = time.perf_counter()
        play_loop_start_ms = int(time.time() * 1000)
        print(f"play loop started at epoch_ms={play_loop_start_ms}")
        while True:
            bpm = self.current_bpm
            beat_interval = 60.0 / bpm
            beat_before_ms = int(time.time() * 1000)
            if self.gui is not None:
                self.gui.flash(beat_before_ms)
            print(f"played haptic feedback at epoch_ms={beat_before_ms} (duration=0ms)")

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

    async def _cancel_scheduled_start_task(self) -> None:
        if not self.scheduled_start_task or self.scheduled_start_task.done():
            self.scheduled_start_task = None
            return
        self.scheduled_start_task.cancel()
        try:
            await self.scheduled_start_task
        except asyncio.CancelledError:
            pass
        self.scheduled_start_task = None

    async def _start_play_loop(self) -> None:
        if self.play_task is None or self.play_task.done():
            self.play_task = self.loop.create_task(self._play_loop())
            self._set_run_state("running")
            self._set_last_event("play loop started")
            print("play loop started")
            return
        print("play loop already running")

    async def _run_scheduled_start(self, payload_target_ms: int, target_ms: int, schedule_id: int) -> None:
        initialize_task = self.loop.create_task(self._initialize())
        try:
            now_ms = int(time.time() * 1000)
            delay_ms = target_ms - now_ms
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            await initialize_task

            if schedule_id != self.current_schedule_id:
                print(f"ignored stale scheduled start schedule_id={schedule_id}")
                return
            if self.current_run != 1:
                print(f"ignored cancelled scheduled start schedule_id={schedule_id}")
                return

            actual_ms = int(time.time() * 1000)
            self._set_schedule_times(payload_target_ms, target_ms, actual_ms)
            print(
                "scheduled start reached "
                f"payload_target_ms={payload_target_ms} "
                f"target_ms={target_ms} actual_ms={actual_ms}"
            )
            self._set_last_event(
                "scheduled start reached "
                f"target_ms={target_ms} actual_ms={actual_ms}"
            )
            await self._start_play_loop()
        except asyncio.CancelledError:
            if not initialize_task.done():
                initialize_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await initialize_task
            raise

    async def _set_bpm_async(self, bpm: int) -> None:
        if bpm <= 0:
            raise ValueError("bpm must be a positive integer")
        self.current_bpm = bpm
        self._set_last_event(f"updated bpm={bpm}")
        print(f"updated bpm={bpm}")

    async def _stop_async(self) -> None:
        self.current_run = 0
        self.current_schedule_id += 1
        self._set_run_state("stopped")
        self._set_last_event("updated run=0")
        print("updated run=0")

        await self._cancel_scheduled_start_task()
        await self._cancel_play_task()

    async def _schedule_start_async(self, payload_target_ms: int) -> None:
        target_ms = payload_target_ms
        now_ms = int(time.time() * 1000)
        lag_ms = now_ms - target_ms
        if lag_ms > STALE_START_THRESHOLD_MS:
            print(
                "ignored stale start timestamp "
                f"payload_target_ms={payload_target_ms} "
                f"target_ms={target_ms} lag_ms={lag_ms}"
            )
            self._set_last_event(
                "ignored stale start timestamp "
                f"payload_target_ms={payload_target_ms} lag_ms={lag_ms}"
            )
            return

        self.current_run = 1
        self.current_schedule_id += 1
        schedule_id = self.current_schedule_id

        await self._cancel_scheduled_start_task()
        self._set_schedule_times(payload_target_ms, target_ms, None)
        self._set_run_state("scheduled")
        self.scheduled_start_task = self.loop.create_task(
            self._run_scheduled_start(payload_target_ms, target_ms, schedule_id)
        )

        delay_ms = max(0, target_ms - now_ms)
        print(
            "scheduled start "
            f"payload_target_ms={payload_target_ms} "
            f"target_ms={target_ms} delay_ms={delay_ms} "
            f"schedule_id={schedule_id}"
        )
        self._set_last_event(
            "scheduled start "
            f"target_ms={target_ms} delay_ms={delay_ms}"
        )

    def set_bpm(self, bpm: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._set_bpm_async(bpm), self.loop)
        future.result(timeout=timeout)

    def stop(self, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._stop_async(), self.loop)
        future.result(timeout=timeout)

    def schedule_start(self, payload_target_ms: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._schedule_start_async(payload_target_ms),
            self.loop,
        )
        future.result(timeout=timeout)

    def close(self) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(self._stop_async(), self.loop)
            future.result(timeout=5.0)
        except Exception:
            pass
        if self.gui is not None:
            self.gui.close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2.0)


def _build_parser() -> argparse.ArgumentParser:
    defaults = _get_mqtt_defaults()
    parser = argparse.ArgumentParser(description="MQTT timing test with one circle GUI.")
    parser.add_argument("--broker", default=defaults["broker"], help="MQTT broker host or URL")
    parser.add_argument("--port", type=int, default=defaults["port"], help="MQTT broker port")
    parser.add_argument("--keepalive", type=int, default=defaults["keepalive"], help="MQTT keepalive in seconds")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=defaults["qos"], help="MQTT QoS level for subscription")
    parser.add_argument("--username", default=defaults["username"], help="MQTT username")
    parser.add_argument("--password", default=defaults["password"], help="MQTT password")
    return parser


def _connect_client(config: dict[str, str | int | None]) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    username = config["username"]
    password = config["password"]
    if username:
        client.username_pw_set(str(username), str(password) if password is not None else None)
    return client


def main() -> int:
    args = _build_parser().parse_args()
    host, port = _parse_broker(str(args.broker), int(args.port))
    config = {
        "broker": host,
        "port": port,
        "keepalive": int(args.keepalive),
        "qos": int(args.qos),
        "username": args.username,
        "password": args.password,
    }

    controller = TimingController()
    stop_event = threading.Event()
    connect_event = threading.Event()
    connect_error: list[str] = []
    root = None
    ui = None
    mqtt_status_lock = threading.Lock()
    mqtt_status_text = "connecting..."

    client = _connect_client(config)

    def _request_stop() -> None:
        if stop_event.is_set():
            return
        stop_event.set()
        try:
            client.disconnect()
        except Exception:
            pass

    def _set_ui_mqtt_status(status: str) -> None:
        nonlocal mqtt_status_text
        with mqtt_status_lock:
            mqtt_status_text = status

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
            _client.subscribe([(TOPIC_BPM, config["qos"]), (TOPIC_RUN, config["qos"])])
            print(f"subscribed to {TOPIC_BPM}, {TOPIC_RUN}")
            _set_ui_mqtt_status("connected")
            connect_event.set()
            return

        if not failed and str(reason_code).strip().lower() in {"success", "0"}:
            _client.subscribe([(TOPIC_BPM, config["qos"]), (TOPIC_RUN, config["qos"])])
            print(f"subscribed to {TOPIC_BPM}, {TOPIC_RUN}")
            _set_ui_mqtt_status("connected")
            connect_event.set()
            return

        error_message = f"MQTT connect failed: {reason_code}"
        connect_error.append(error_message)
        _set_ui_mqtt_status(f"connection failed: {reason_code}")
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
                action, payload_target_ms = _parse_run_payload(payload)
                if action == "stop":
                    controller.stop()
                else:
                    if payload_target_ms is None:
                        raise ValueError("missing start timestamp")
                    controller.schedule_start(payload_target_ms)
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
        _set_ui_mqtt_status(f"disconnected: {reason_code}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    def _stop_handler(_signum: int, _frame: object) -> None:
        _request_stop()

    signal.signal(signal.SIGINT, _stop_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop_handler)

    if tk is not None:
        root = tk.Tk()
        root.title("Circle One Timing Test")
        root.geometry("420x260")
        root.resizable(False, False)
        ui = tk.Frame(root, padx=12, pady=12)
        ui.pack(fill=tk.BOTH, expand=True)
        tk.Label(ui, text="MQTT", font=("Helvetica", 12)).grid(row=0, column=0, sticky="w")
        mqtt_status_var = tk.StringVar(value="connecting...")
        tk.Label(ui, textvariable=mqtt_status_var, font=("Helvetica", 10)).grid(row=0, column=1, sticky="w")
        tk.Label(ui, text="Run State", font=("Helvetica", 12)).grid(row=1, column=0, sticky="w")
        run_state_var = tk.StringVar(value="stopped")
        tk.Label(ui, textvariable=run_state_var, font=("Helvetica", 10)).grid(row=1, column=1, sticky="w")
        tk.Label(ui, text="Circle", font=("Helvetica", 12)).grid(row=2, column=0, sticky="w")
        tk.Label(ui, text="watch the window", font=("Helvetica", 10)).grid(row=2, column=1, sticky="w")

        def _sync_labels() -> None:
            snapshot_state = controller.current_run_state
            with mqtt_status_lock:
                current_status = mqtt_status_text
            mqtt_status_var.set(current_status)
            run_state_var.set(snapshot_state)
            if stop_event.is_set():
                if root.winfo_exists():
                    root.destroy()
                return
            root.after(100, _sync_labels)

        def _on_close() -> None:
            _request_stop()
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)
        root.after(100, _sync_labels)

    try:
        print(f"connecting to MQTT broker {host}:{port}")
        client.connect(host, port, int(args.keepalive))
        client.loop_start()

        if not connect_event.wait(timeout=5):
            print("error: timeout waiting for MQTT connection")
            if tk is None:
                return 1
            _set_ui_mqtt_status("connection failed: timeout")
        if connect_error:
            print(f"error: {connect_error[0]}")
            return 1

        print("subscriber running. press Ctrl+C to stop.")

        if tk is None:
            while not stop_event.is_set():
                time.sleep(0.2)
            return 0

        assert root is not None
        root.mainloop()
        return 0
    finally:
        client.loop_stop()
        client.disconnect()
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sqlite3
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    tk = None
    messagebox = None

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
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOTOR_LEN = 32
DEFAULT_BPM = 120
MIN_EPOCH_MS = 10**11
STALE_START_THRESHOLD_MS = 5000

DEFAULT_CONFIG_DB_NAME = "config.db"
DEFAULT_CONFIG_DIRNAME = "myPyHaptics"
PHASE_SHIFT_MIN_MS = -2000
PHASE_SHIFT_MAX_MS = 2000
PHASE_SHIFT_STEP_MS = 10


def _default_config_db_path() -> Path:
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / DEFAULT_CONFIG_DIRNAME / DEFAULT_CONFIG_DB_NAME
    return PROJECT_ROOT / "data" / DEFAULT_CONFIG_DB_NAME


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class BrokerConfig:
    host: str
    port: int
    keepalive: int
    qos: int
    username: str | None
    password: str | None


class ConfigStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load_phase_shift_ms(self, default: int = 0) -> int:
        with self._lock:
            self._initialize()
            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT value FROM app_config WHERE key = ?",
                    ("phase_shift_ms",),
                )
                row = cursor.fetchone()
                if row is None:
                    return default
                try:
                    return int(row[0])
                except (TypeError, ValueError):
                    return default

    def save_phase_shift_ms(self, value: int) -> None:
        with self._lock:
            self._initialize()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO app_config(key, value, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    ("phase_shift_ms", str(value), _utc_now_iso()),
                )
                conn.commit()


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


def _parse_run_payload(payload: str) -> tuple[str, int | None]:
    normalized = payload.strip().lower()
    if normalized in {"0", "false", "off", "stop", "no"}:
        return "stop", None

    try:
        publish_ms = int(payload.strip())
    except ValueError as exc:
        raise ValueError(f"invalid run payload: {payload!r}") from exc

    if publish_ms < MIN_EPOCH_MS:
        raise ValueError(
            f"invalid start timestamp (expected epoch-ms): {publish_ms}"
        )
    return "start", publish_ms


class HapticsController:
    def __init__(
        self,
        app_id: str,
        api_key: str,
        app_name: str,
        config_store: ConfigStore,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.app_name = app_name
        self.config_store = config_store

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

        self._status_lock = threading.Lock()
        self.current_bpm = DEFAULT_BPM
        self.current_run = 0
        self.current_run_state = "stopped"
        self.phase_shift_ms = self.config_store.load_phase_shift_ms(default=0)
        self.pending_phase_shift_ms = 0
        self.session_phase_shift_delta_ms = 0
        self.last_payload_target_ms: int | None = None
        self.last_target_ms: int | None = None
        self.last_actual_ms: int | None = None
        self.last_event = f"loaded phase_shift_ms={self.phase_shift_ms}"

        self.initialized = False
        self.play_task: asyncio.Task[None] | None = None
        self.scheduled_start_task: asyncio.Task[None] | None = None
        self.current_schedule_id = 0

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

    def _set_schedule_times(
        self,
        payload_target_ms: int,
        target_ms: int,
        actual_ms: int | None,
    ) -> None:
        with self._status_lock:
            self.last_payload_target_ms = payload_target_ms
            self.last_target_ms = target_ms
            self.last_actual_ms = actual_ms

    def _get_effective_phase_shift_ms(self) -> int:
        with self._status_lock:
            return self.phase_shift_ms + self.session_phase_shift_delta_ms

    def _consume_pending_phase_shift_ms(self) -> int:
        with self._status_lock:
            shift_ms = self.pending_phase_shift_ms
            self.pending_phase_shift_ms = 0
            return shift_ms

    def _compute_target_ms(self, payload_target_ms: int) -> int:
        effective_shift = self._get_effective_phase_shift_ms()
        return payload_target_ms - effective_shift

    def _commit_session_phase_shift(self) -> None:
        with self._status_lock:
            delta_ms = self.session_phase_shift_delta_ms
            if delta_ms == 0:
                self.pending_phase_shift_ms = 0
                return
            self.phase_shift_ms += delta_ms
            self.session_phase_shift_delta_ms = 0
            self.pending_phase_shift_ms = 0
            committed_phase = self.phase_shift_ms

        self.config_store.save_phase_shift_ms(committed_phase)
        print(
            "committed phase shift to config "
            f"delta_ms={delta_ms} phase_shift_ms={committed_phase}"
        )
        self._set_last_event(f"committed phase_shift_ms={committed_phase}")

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
            shift_ms = self._consume_pending_phase_shift_ms()
            if shift_ms != 0:
                next_tick -= shift_ms / 1000.0
                print(f"applied pending phase shift shift_ms={shift_ms}")
                self._set_last_event(f"applied pending phase shift shift_ms={shift_ms}")

            bpm = self.current_bpm
            beat_interval = 60.0 / bpm
            values = [20] * MOTOR_LEN
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

    async def _run_scheduled_start(
        self,
        payload_target_ms: int,
        target_ms: int,
        schedule_id: int,
    ) -> None:
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

    async def _set_phase_shift_async(self, phase_shift_ms: int) -> None:
        if phase_shift_ms < PHASE_SHIFT_MIN_MS or phase_shift_ms > PHASE_SHIFT_MAX_MS:
            raise ValueError(
                f"phase_shift_ms must be in [{PHASE_SHIFT_MIN_MS}, {PHASE_SHIFT_MAX_MS}]"
            )

        running = self.play_task is not None and not self.play_task.done()
        scheduled = (
            self.scheduled_start_task is not None
            and not self.scheduled_start_task.done()
        )

        if running:
            with self._status_lock:
                effective = self.phase_shift_ms + self.session_phase_shift_delta_ms
                delta_ms = phase_shift_ms - effective
                if delta_ms == 0:
                    return
                self.pending_phase_shift_ms += delta_ms
                self.session_phase_shift_delta_ms += delta_ms
                queued_ms = self.pending_phase_shift_ms
            print(
                "queued phase shift update during running "
                f"requested_ms={phase_shift_ms} delta_ms={delta_ms} "
                f"pending_phase_shift_ms={queued_ms}"
            )
            self._set_last_event(
                "queued phase shift update "
                f"requested_ms={phase_shift_ms} delta_ms={delta_ms}"
            )
            return

        with self._status_lock:
            self.phase_shift_ms = phase_shift_ms
            self.pending_phase_shift_ms = 0
            self.session_phase_shift_delta_ms = 0
            last_payload_target_ms = (
                self.last_payload_target_ms if scheduled else None
            )

        self.config_store.save_phase_shift_ms(phase_shift_ms)
        print(f"updated phase_shift_ms={phase_shift_ms}")
        self._set_last_event(f"updated phase_shift_ms={phase_shift_ms}")

        if last_payload_target_ms is not None:
            await self._schedule_start_async(last_payload_target_ms)

    async def _stop_async(self) -> None:
        self.current_run = 0
        self.current_schedule_id += 1
        self._set_run_state("stopped")
        self._set_last_event("updated run=0")
        print("updated run=0")

        await self._cancel_scheduled_start_task()
        await self._cancel_play_task()
        if self.initialized:
            await bhaptics_python.stop_all()
            print("play loop stopped")

        self._commit_session_phase_shift()

    async def _schedule_start_async(self, payload_target_ms: int) -> None:
        target_ms = self._compute_target_ms(payload_target_ms)
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
        effective_shift = self._get_effective_phase_shift_ms()
        print(
            "scheduled start "
            f"payload_target_ms={payload_target_ms} "
            f"target_ms={target_ms} delay_ms={delay_ms} "
            f"schedule_id={schedule_id} phase_shift_ms={effective_shift}"
        )
        self._set_last_event(
            "scheduled start "
            f"target_ms={target_ms} delay_ms={delay_ms} phase_shift_ms={effective_shift}"
        )

    async def _close_async(self) -> None:
        self.current_run = 0
        self.current_schedule_id += 1
        self._set_run_state("stopped")

        await self._cancel_scheduled_start_task()
        await self._cancel_play_task()
        if self.initialized:
            await bhaptics_python.stop_all()

        self._commit_session_phase_shift()

        if self.initialized:
            await bhaptics_python.close()
            self.initialized = False

    def set_bpm(self, bpm: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._set_bpm_async(bpm), self.loop)
        future.result(timeout=timeout)

    def set_phase_shift(self, phase_shift_ms: int, timeout: float = 5.0) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._set_phase_shift_async(phase_shift_ms),
            self.loop,
        )
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

    def get_status_snapshot(self) -> dict[str, int | str | None]:
        with self._status_lock:
            effective_phase_shift = self.phase_shift_ms + self.session_phase_shift_delta_ms
            return {
                "current_bpm": self.current_bpm,
                "run_state": self.current_run_state,
                "phase_shift_ms": self.phase_shift_ms,
                "pending_phase_shift_ms": self.pending_phase_shift_ms,
                "effective_phase_shift_ms": effective_phase_shift,
                "last_payload_target_ms": self.last_payload_target_ms,
                "last_target_ms": self.last_target_ms,
                "last_actual_ms": self.last_actual_ms,
                "last_event": self.last_event,
            }

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

class SubscriberControlUI:
    REFRESH_MS = 200

    def __init__(
        self,
        root: tk.Tk,
        controller: HapticsController,
        request_stop,
    ) -> None:
        self.root = root
        self.controller = controller
        self.request_stop = request_stop

        self.bpm_var = tk.StringVar(value="-")
        self.run_state_var = tk.StringVar(value="-")
        self.phase_shift_entry_var = tk.StringVar(value="0")
        self.applied_phase_shift_var = tk.StringVar(value="-")
        self.pending_phase_shift_var = tk.StringVar(value="-")
        self.target_var = tk.StringVar(value="-")
        self.actual_var = tk.StringVar(value="-")
        self.offset_var = tk.StringVar(value="-")
        self.last_event_var = tk.StringVar(value="-")
        self.apply_status_var = tk.StringVar(value="")

        self._build_layout()
        self._refresh()

    def _build_layout(self) -> None:
        self.root.title("myPyHaptics Subscriber")
        self.root.geometry("640x340")
        self.root.resizable(False, False)

        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="Current BPM").grid(row=0, column=0, sticky="w")
        tk.Label(frame, textvariable=self.bpm_var).grid(row=0, column=1, sticky="w")

        tk.Label(frame, text="Run State").grid(row=1, column=0, sticky="w")
        tk.Label(frame, textvariable=self.run_state_var).grid(row=1, column=1, sticky="w")

        tk.Label(frame, text="Phase Shift (ms)").grid(row=2, column=0, sticky="w")
        controls = tk.Frame(frame)
        controls.grid(row=2, column=1, sticky="w")

        tk.Button(
            controls,
            text="-",
            width=3,
            command=lambda: self._step_phase_shift(-PHASE_SHIFT_STEP_MS),
        ).pack(side=tk.LEFT)
        phase_entry = tk.Entry(
            controls,
            textvariable=self.phase_shift_entry_var,
            width=10,
            justify="right",
        )
        self.phase_entry = phase_entry
        phase_entry.pack(side=tk.LEFT, padx=6)
        phase_entry.bind("<Return>", lambda _event: self._apply_phase_shift())
        tk.Button(
            controls,
            text="+",
            width=3,
            command=lambda: self._step_phase_shift(PHASE_SHIFT_STEP_MS),
        ).pack(side=tk.LEFT)
        tk.Button(
            controls,
            text="Apply",
            width=8,
            command=self._apply_phase_shift,
        ).pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(frame, text="Applied Phase Shift").grid(row=3, column=0, sticky="w")
        tk.Label(frame, textvariable=self.applied_phase_shift_var).grid(
            row=3, column=1, sticky="w"
        )

        tk.Label(frame, text="Pending Phase Shift").grid(row=4, column=0, sticky="w")
        tk.Label(frame, textvariable=self.pending_phase_shift_var).grid(
            row=4, column=1, sticky="w"
        )

        tk.Label(frame, text="Last target_ms").grid(row=5, column=0, sticky="w")
        tk.Label(frame, textvariable=self.target_var).grid(row=5, column=1, sticky="w")

        tk.Label(frame, text="Last actual_ms").grid(row=6, column=0, sticky="w")
        tk.Label(frame, textvariable=self.actual_var).grid(row=6, column=1, sticky="w")

        tk.Label(frame, text="actual-target (ms)").grid(row=7, column=0, sticky="w")
        tk.Label(frame, textvariable=self.offset_var).grid(row=7, column=1, sticky="w")

        tk.Label(frame, text="Last Event").grid(row=8, column=0, sticky="w")
        tk.Label(frame, textvariable=self.last_event_var, anchor="w").grid(
            row=8, column=1, sticky="w"
        )

        tk.Label(frame, textvariable=self.apply_status_var, fg="#1a5f7a").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _clamp_phase_shift(self, value: int) -> int:
        if value < PHASE_SHIFT_MIN_MS:
            return PHASE_SHIFT_MIN_MS
        if value > PHASE_SHIFT_MAX_MS:
            return PHASE_SHIFT_MAX_MS
        return value

    def _parse_phase_shift_entry(self) -> int:
        raw = self.phase_shift_entry_var.get().strip()
        if not raw:
            raise ValueError("phase shift is empty")
        return int(raw)

    def _step_phase_shift(self, step: int) -> None:
        try:
            current = self._parse_phase_shift_entry()
        except ValueError:
            snapshot = self.controller.get_status_snapshot()
            current = int(snapshot["effective_phase_shift_ms"] or 0)
        updated = self._clamp_phase_shift(current + step)
        self.phase_shift_entry_var.set(str(updated))

    def _apply_phase_shift(self) -> None:
        try:
            requested = self._clamp_phase_shift(self._parse_phase_shift_entry())
            self.controller.set_phase_shift(requested)
            self.phase_shift_entry_var.set(str(requested))
            self.apply_status_var.set(f"Applied phase_shift_ms={requested}")
        except ValueError as exc:
            self.apply_status_var.set(f"Invalid phase shift: {exc}")
            if messagebox is not None:
                messagebox.showerror("Invalid phase shift", str(exc))
        except Exception as exc:
            self.apply_status_var.set(f"Failed to apply phase shift: {exc}")
            if messagebox is not None:
                messagebox.showerror("Apply failed", str(exc))

    def _refresh(self) -> None:
        snapshot = self.controller.get_status_snapshot()

        self.bpm_var.set(str(snapshot["current_bpm"]))
        self.run_state_var.set(str(snapshot["run_state"]))
        self.applied_phase_shift_var.set(str(snapshot["effective_phase_shift_ms"]))
        self.pending_phase_shift_var.set(str(snapshot["pending_phase_shift_ms"]))
        self.last_event_var.set(str(snapshot["last_event"]))

        target_ms = snapshot["last_target_ms"]
        actual_ms = snapshot["last_actual_ms"]
        self.target_var.set("-" if target_ms is None else str(target_ms))
        self.actual_var.set("-" if actual_ms is None else str(actual_ms))
        if target_ms is None or actual_ms is None:
            self.offset_var.set("-")
        else:
            self.offset_var.set(str(actual_ms - target_ms))

        if self.root.focus_get() is not self.phase_entry:
            self.phase_shift_entry_var.set(str(snapshot["effective_phase_shift_ms"]))

        self.root.after(self.REFRESH_MS, self._refresh)

    def _on_close(self) -> None:
        self.request_stop()
        self.root.destroy()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Subscribe MQTT topics and control bHaptics playback."
    )
    parser.add_argument(
        "--broker",
        default="mqtt-web.makinteract.com",
        help="MQTT broker host or URL (default: mqtt-web.makinteract.com)",
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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without control UI window",
    )
    parser.add_argument(
        "--config-db",
        default=str(_default_config_db_path()),
        help="SQLite config file path (default: %%APPDATA%%/myPyHaptics/config.db)",
    )
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

    config_store = ConfigStore(Path(args.config_db))
    controller = HapticsController(app_id, api_key, app_name, config_store)
    stop_event = threading.Event()
    connect_event = threading.Event()
    connect_error: list[str] = []

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.username:
        client.username_pw_set(config.username, config.password)

    def _request_stop() -> None:
        if stop_event.is_set():
            return
        stop_event.set()
        try:
            client.disconnect()
        except Exception:
            pass

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

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    def _stop_handler(_signum: int, _frame: object) -> None:
        _request_stop()

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

        if args.headless or tk is None:
            if not args.headless and tk is None:
                print("warning: tkinter not available, running in headless mode")
            while not stop_event.is_set():
                time.sleep(0.2)
            return 0

        root = tk.Tk()
        SubscriberControlUI(root=root, controller=controller, request_stop=_request_stop)

        def _poll_stop() -> None:
            if stop_event.is_set():
                if root.winfo_exists():
                    root.destroy()
                return
            root.after(200, _poll_stop)

        root.after(200, _poll_stop)
        root.mainloop()
        return 0
    finally:
        client.loop_stop()
        client.disconnect()
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())

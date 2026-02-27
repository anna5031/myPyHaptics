from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from threading import Event
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    tk = None
    messagebox = None


TOPIC_BPM = "bhaptics/bpm"
TOPIC_RUN = "bhaptics/run"


@dataclass(frozen=True)
class BrokerConfig:
    host: str
    port: int
    keepalive: int
    qos: int
    retain: bool
    username: str | None
    password: str | None


class PublishUI:
    def __init__(self, root: tk.Tk, client: mqtt.Client, config: BrokerConfig) -> None:
        self.root = root
        self.client = client
        self.config = config
        self.status_var = tk.StringVar(value="ready")
        self.bpm_var = tk.StringVar(value="120")
        self.delay_var = tk.StringVar(value="3")
        self._build_layout()

    def _build_layout(self) -> None:
        self.root.title("myPyHaptics Publisher")
        self.root.geometry("520x260")
        self.root.resizable(False, False)

        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="BPM").grid(row=0, column=0, sticky="w")
        tk.Entry(frame, textvariable=self.bpm_var, width=10, justify="right").grid(
            row=0,
            column=1,
            sticky="w",
        )
        tk.Button(frame, text="Publish BPM", command=self._publish_bpm).grid(
            row=0, column=2, padx=(10, 0), sticky="w"
        )

        tk.Label(frame, text="Start Delay (sec)").grid(row=1, column=0, sticky="w")
        tk.Entry(frame, textvariable=self.delay_var, width=10, justify="right").grid(
            row=1,
            column=1,
            sticky="w",
        )
        tk.Button(
            frame,
            text="Publish Target Start",
            command=self._publish_target_start,
        ).grid(row=1, column=2, padx=(10, 0), sticky="w")

        tk.Button(frame, text="Start Now", command=self._start_now).grid(
            row=2, column=0, pady=(14, 0), sticky="w"
        )
        tk.Button(frame, text="Stop", command=self._stop).grid(
            row=2, column=1, pady=(14, 0), sticky="w"
        )

        tk.Label(frame, text="Status").grid(row=3, column=0, sticky="nw", pady=(14, 0))
        tk.Label(
            frame,
            textvariable=self.status_var,
            justify="left",
            anchor="w",
            wraplength=380,
        ).grid(row=3, column=1, columnspan=2, sticky="w", pady=(14, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _publish_bpm(self) -> None:
        try:
            bpm = int(self.bpm_var.get().strip())
            if bpm <= 0:
                raise ValueError("bpm must be positive")
            _publish_value(self.client, TOPIC_BPM, bpm, self.config.qos, self.config.retain)
            self._set_status(f"published {TOPIC_BPM}={bpm}")
        except Exception as exc:
            self._set_status(f"failed to publish bpm: {exc}")
            if messagebox is not None:
                messagebox.showerror("Publish BPM failed", str(exc))

    def _publish_start(self, delay_sec: float) -> None:
        payload = _resolve_run_payload(run=1, delay_sec=delay_sec)
        _publish_value(self.client, TOPIC_RUN, payload, self.config.qos, self.config.retain)
        self._set_status(
            f"published {TOPIC_RUN} target_ts_ms={payload} (delay_s={delay_sec:g})"
        )

    def _start_now(self) -> None:
        try:
            self._publish_start(delay_sec=0.0)
        except Exception as exc:
            self._set_status(f"failed to publish start: {exc}")
            if messagebox is not None:
                messagebox.showerror("Start failed", str(exc))

    def _publish_target_start(self) -> None:
        try:
            delay_sec = float(self.delay_var.get().strip())
            if delay_sec < 0:
                raise ValueError("delay must be >= 0")
            self._publish_start(delay_sec=delay_sec)
        except Exception as exc:
            self._set_status(f"failed to publish delayed start: {exc}")
            if messagebox is not None:
                messagebox.showerror("Delayed Start failed", str(exc))

    def _stop(self) -> None:
        try:
            _publish_value(self.client, TOPIC_RUN, 0, self.config.qos, self.config.retain)
            self._set_status(f"published {TOPIC_RUN}=0")
        except Exception as exc:
            self._set_status(f"failed to publish stop: {exc}")
            if messagebox is not None:
                messagebox.showerror("Stop failed", str(exc))

    def _on_close(self) -> None:
        self.root.destroy()


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish bHaptics control values to MQTT topics."
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
        help="MQTT QoS level (default: 1)",
    )
    parser.add_argument(
        "--retain",
        action="store_true",
        help="Publish with retained flag",
    )
    parser.add_argument("--username", help="MQTT username", default=None)
    parser.add_argument("--password", help="MQTT password", default=None)
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch interactive publisher UI",
    )
    parser.add_argument("--bpm", type=int, help="Value for /bhaptics/bpm")
    parser.add_argument(
        "--delay-s",
        type=float,
        default=None,
        help="Publish start target as floor(current_time)+delay_s seconds",
    )
    parser.add_argument(
        "--run",
        type=int,
        choices=[0, 1],
        help="Run command (0=stop now, 1=start using target timestamp payload)",
    )
    return parser


def _connect_client(config: BrokerConfig) -> mqtt.Client:
    connected = Event()
    connect_error: list[str] = []

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    if config.username:
        client.username_pw_set(config.username, config.password)

    def _connect_ok(reason_code: object) -> bool:
        if reason_code == 0:
            return True

        is_failure = getattr(reason_code, "is_failure", None)
        if isinstance(is_failure, bool):
            return not is_failure
        if callable(is_failure):
            try:
                return not bool(is_failure())
            except TypeError:
                pass

        code_value = getattr(reason_code, "value", None)
        if isinstance(code_value, int):
            return code_value == 0

        return str(reason_code).strip().lower() in {"success", "0"}

    def _reason_code_text(reason_code: object) -> str:
        code_value = getattr(reason_code, "value", None)
        if isinstance(code_value, int):
            return f"{reason_code} (code={code_value})"
        return str(reason_code)

    def on_connect(
        _client: mqtt.Client,
        _userdata: object,
        _flags: dict[str, int],
        reason_code: object,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if _connect_ok(reason_code):
            connected.set()
            return
        connect_error.append(f"MQTT connect failed: {_reason_code_text(reason_code)}")
        connected.set()

    client.on_connect = on_connect
    client.connect(config.host, config.port, config.keepalive)
    client.loop_start()

    if not connected.wait(timeout=5):
        client.loop_stop()
        client.disconnect()
        raise TimeoutError("timeout waiting for MQTT connection")

    if connect_error:
        client.loop_stop()
        client.disconnect()
        raise ConnectionError(connect_error[0])

    return client


def _publish_value(
    client: mqtt.Client,
    topic: str,
    value: int,
    qos: int,
    retain: bool,
) -> None:
    payload = str(value)
    info = client.publish(topic, payload=payload, qos=qos, retain=retain)
    info.wait_for_publish(timeout=5)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"failed to publish {topic}: rc={info.rc}")


def _resolve_run_payload(run: int, delay_sec: float | None = None) -> int:
    if run == 0:
        return 0
    now_ms = int(time.time() * 1000)
    if delay_sec is None:
        return now_ms
    base_ms = (now_ms // 1000) * 1000
    return base_ms + int(delay_sec * 1000)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.ui and args.bpm is None and args.run is None and args.delay_s is None:
        parser.error("at least one of --bpm, --run, or --delay-s is required")
    if args.bpm is not None and args.bpm <= 0:
        parser.error("--bpm must be a positive integer")
    if args.delay_s is not None and args.delay_s < 0:
        parser.error("--delay-s must be >= 0")
    if args.delay_s is not None and args.run == 0:
        parser.error("--delay-s cannot be used with --run 0")

    host, port = _parse_broker(args.broker, args.port)
    config = BrokerConfig(
        host=host,
        port=port,
        keepalive=args.keepalive,
        qos=args.qos,
        retain=args.retain,
        username=args.username,
        password=args.password,
    )

    client: mqtt.Client | None = None
    try:
        client = _connect_client(config)

        if args.ui:
            if tk is None:
                raise RuntimeError("tkinter is not available")
            root = tk.Tk()
            PublishUI(root=root, client=client, config=config)
            root.mainloop()
            return 0

        if args.bpm is not None:
            _publish_value(client, TOPIC_BPM, args.bpm, config.qos, config.retain)
            print(f"published {TOPIC_BPM}={args.bpm}")

        should_publish_start = (args.run == 1) or (args.run is None and args.delay_s is not None)
        if args.run == 0:
            run_payload = 0
            _publish_value(client, TOPIC_RUN, run_payload, config.qos, config.retain)
            print(f"published {TOPIC_RUN}=0")
        elif should_publish_start:
            run_payload = _resolve_run_payload(1, delay_sec=args.delay_s)
            _publish_value(client, TOPIC_RUN, run_payload, config.qos, config.retain)
            delay_text = 0.0 if args.delay_s is None else args.delay_s
            print(
                f"published {TOPIC_RUN} target_ts_ms={run_payload} "
                f"(delay_s={delay_text:g})"
            )

        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

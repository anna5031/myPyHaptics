from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from threading import Event
from urllib.parse import urlparse

import paho.mqtt.client as mqtt


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
    parser.add_argument("--bpm", type=int, help="Value for /bhaptics/bpm")
    parser.add_argument(
        "--run",
        type=int,
        choices=[0, 1],
        help="Run command (0=stop now, 1=publish current epoch-ms as start timestamp)",
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


def _resolve_run_payload(run: int) -> int:
    if run == 0:
        return 0
    return int(time.time() * 1000)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.bpm is None and args.run is None:
        parser.error("at least one of --bpm or --run is required")
    if args.bpm is not None and args.bpm <= 0:
        parser.error("--bpm must be a positive integer")

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

        if args.bpm is not None:
            _publish_value(client, TOPIC_BPM, args.bpm, config.qos, config.retain)
            print(f"published {TOPIC_BPM}={args.bpm}")

        if args.run is not None:
            run_payload = _resolve_run_payload(args.run)
            _publish_value(client, TOPIC_RUN, run_payload, config.qos, config.retain)
            if args.run == 1:
                print(f"published {TOPIC_RUN} start_ts_ms={run_payload}")
            else:
                print(f"published {TOPIC_RUN}=0")

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

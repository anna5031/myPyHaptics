import argparse
import json
import time
import sys

import paho.mqtt.client as mqtt

import config

TOPIC = "bHaptics/command"


def publish(message: dict):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(config.MQTT_ADDRESS, config.MQTT_PORT)
    payload = json.dumps(message)
    client.publish(TOPIC, payload)
    client.disconnect()
    print(f"[Publisher] Sent to {TOPIC}: {payload}")


def cmd_start(args):
    delay_sec = args.delay / 1000.0
    scheduled_time = time.time() + delay_sec

    publish({
        "command": "start",
        "bpm": args.bpm,
        "time": scheduled_time,
    })


def cmd_stop(_args):
    publish({
        "command": "stop",
    })


def main():
    parser = argparse.ArgumentParser(description="bHaptics MQTT Publisher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start the metronome")
    start_parser.add_argument("--bpm", type=int, required=True, help="Beats per minute")
    start_parser.add_argument("--delay", type=int, default=0, help="Delay in milliseconds before start")
    start_parser.set_defaults(func=cmd_start)

    stop_parser = subparsers.add_parser("stop", help="Stop the metronome")
    stop_parser.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

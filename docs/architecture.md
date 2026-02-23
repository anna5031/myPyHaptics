# myPyHaptics Architecture

## 1) Purpose
`myPyHaptics` provides a minimal MQTT-based control flow for bHaptics playback.

- `src/publish.py`: publishes control messages
- `src/subscribe.py`: subscribes to control messages and controls haptics playback

At this stage, architecture is defined first and implementation follows.

## 2) MQTT Broker
- Broker URL: `https://mqtt.makinteract.com/`

Note: MQTT clients usually connect with `mqtt://`, `tcp://`, or `wss://` endpoints. Final connection format depends on the chosen MQTT library.

## 3) Topic Design
### Shared Publish/Subscribe Topics
- `/bhaptics/bpm`
  - Meaning: playback BPM value
  - Payload: integer (example: `120`)
- `/bhaptics/run`
  - Meaning: start/stop flag
  - Payload: integer or boolean-like value
  - Rule: if `run == 1`, start `_play_loop`

## 4) Component Responsibilities
### A. Publisher (`src/publish.py`)
- Publish BPM to `/bhaptics/bpm`
- Publish run state to `/bhaptics/run`
- Forward external control input (UI/CLI/test script) to MQTT

### B. Subscriber (`src/subscribe.py`)
- Subscribe to `/bhaptics/bpm` and `/bhaptics/run`
- Keep latest BPM in memory
- Start `_play_loop(bpm)` when `run == 1`
- Manage playback task lifecycle to prevent duplicate loop tasks

## 5) Intended Runtime Sequence
1. Publisher sends BPM on `/bhaptics/bpm`
2. Publisher sends `1` on `/bhaptics/run`
3. Subscriber receives run message and checks `run == 1`
4. Subscriber starts `_play_loop` with latest BPM
5. Later BPM updates are reflected on subsequent loop intervals (exact implementation detail to be finalized in code)

## 6) Subscriber State Model
- `current_bpm: int`
- `current_run: int`
- `play_task: asyncio.Task | None`

Core invariants:
- If `run == 1` and `play_task is None`, create a new `_play_loop` task
- If `run != 1`, stop the playback task (exact stop behavior to be finalized)

## 7) Error Handling and Validation (Draft)
- Ignore BPM payload if not an integer; log warning
- Ignore BPM if `<= 0`; keep current/default BPM
- Ignore run payload if parsing fails
- Define state resynchronization strategy after reconnect (later)

## 8) Planned Implementation Scope
- `src/publish.py`
  - MQTT client connect/reconnect
  - Helper functions to publish both topics
- `src/subscribe.py`
  - Subscription callbacks for both topics
  - `run == 1` trigger to start `_play_loop`
  - Duplicate-task prevention and stop handling

## 9) Test Points
- Verify exactly one `_play_loop` runs after `/bhaptics/run = 1`
- Verify BPM changes on `/bhaptics/bpm` affect loop interval as expected
- Verify invalid payloads do not crash subscriber

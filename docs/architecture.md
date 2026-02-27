# myPyHaptics Architecture

## 1) Purpose
`myPyHaptics` provides a minimal MQTT-based control flow for bHaptics playback.

- `src/publish.py`: publishes control messages
- `src/subscribe.py`: subscribes to control messages and controls haptics playback

At this stage, architecture is defined first and implementation follows.

## 2) MQTT Broker
- Broker URL: `https://mqtt-web.makinteract.com/`

Note: MQTT clients usually connect with `mqtt://`, `tcp://`, or `wss://` endpoints. Final connection format depends on the chosen MQTT library.

## 3) Topic Design
### Shared Publish/Subscribe Topics
- `/bhaptics/bpm`
  - Meaning: playback BPM value
  - Payload: integer (example: `120`)
- `/bhaptics/run`
  - Meaning: start scheduling / stop command
  - Payload:
    - `0`: stop now
    - `<unix_epoch_milliseconds>`: absolute target start time from publisher
  - Rule:
    - Publisher computes target time as `target_ms = floor(current_time_ms to second) + delay_s * 1000`
    - Subscriber starts vibration at payload target time (with optional local `phase_shift_ms` compensation)

## 4) Component Responsibilities
### A. Publisher (`src/publish.py`)
- Publish BPM to `/bhaptics/bpm`
- Publish stop (`0`) or start timestamp (`unix_epoch_milliseconds`) to `/bhaptics/run`
- For delayed start, compute target timestamp on publisher and publish immediately
- Forward external control input (UI/CLI/test script) to MQTT

### B. Subscriber (`src/subscribe.py`)
- Subscribe to `/bhaptics/bpm` and `/bhaptics/run`
- Keep latest BPM in memory
- For start timestamp payload, schedule `_play_loop` at payload target time
- For stop payload (`0`), cancel scheduled start and stop playback
- Manage both scheduling and playback task lifecycle to prevent duplicates

## 5) Intended Runtime Sequence
1. Publisher sends BPM on `/bhaptics/bpm`
2. Publisher computes `target_ms = floor_to_second(now) + delay_s` and publishes it on `/bhaptics/run`
3. Subscriber receives target timestamp payload
4. Subscriber waits until `target_ms`
5. Subscriber starts `_play_loop` with latest BPM
6. Later BPM updates are reflected on subsequent loop intervals (exact implementation detail to be finalized in code)

## 6) Subscriber State Model
- `current_bpm: int`
- `current_run: int` (stop state)
- `play_task: asyncio.Task | None`
- `scheduled_start_task: asyncio.Task | None`
- `current_schedule_id: int`

Core invariants:
- Only one scheduled start task is active at a time
- If a new start timestamp arrives, cancel previous `scheduled_start_task` and keep only the latest
- `schedule_id` check prevents stale scheduled tasks from starting playback
- If stop (`0`) arrives, cancel `scheduled_start_task` and stop `play_task`
- If start time is already in the past when received, start immediately (with warning log)

## 7) Error Handling and Validation (Draft)
- Ignore BPM payload if not an integer; log warning
- Ignore BPM if `<= 0`; keep current/default BPM
- Accept run payload as either stop (`0`) or epoch-ms start timestamp
- Ignore run payload if parsing fails
- Optionally ignore too-old timestamps (for example, older than now - 5000ms)
- Define state resynchronization strategy after reconnect (later)

## 8) Planned Implementation Scope
- `src/publish.py`
  - MQTT client connect/reconnect
  - Helper functions to publish both topics
  - On delayed start command, publish computed target epoch-ms
- `src/subscribe.py`
  - Subscription callbacks for both topics
  - Timestamp-based start scheduling from payload target time
  - Reservation task cancellation/replacement on newer start timestamp
  - Duplicate-task prevention and stop handling

## 9) Test Points
- Verify exactly one `_play_loop` runs after timestamp-based `/bhaptics/run` start
- Verify BPM changes on `/bhaptics/bpm` affect loop interval as expected
- Verify invalid payloads do not crash subscriber
- Verify new start timestamp cancels/replaces previous scheduled start
- Verify stop (`0`) cancels both scheduled start and active playback
- Verify two subscribers start with small time skew at scheduled target

## 10) Time Sync Requirement
- Scheduled simultaneous start depends on aligned system clocks
- All publisher/subscriber hosts should use NTP synchronization
- Epoch-ms based scheduling accuracy degrades when host clocks are skewed

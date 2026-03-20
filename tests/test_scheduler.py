import asyncio
import time
import pytest
from src.scheduler.scheduler import Scheduler

@pytest.mark.asyncio
async def test_scheduler_delays():
    """Testing that the scheduler can cleanly execute 3s, 5s, 10s, and 30s delays in parallel exactly on schedule."""
    scheduler = Scheduler()
    events = []
    
    def make_callback(delay_sec):
        def cb():
            executed_time = time.time()
            events.append((delay_sec, executed_time))
            print(f"[Callback Fired] Expected: {delay_sec}s -> Actual Delay: {executed_time - start_time:.4f}s")
        return cb

    start_time = time.time()
    
    # Schedule all of them concurrently as requested
    delays = [3, 5, 10]
    
    print("\n[Scheduler Test] Scheduling tests at exactly T=0...")
    for d in delays:
        target = start_time + d
        print(f"[Scheduler Test] Scheduling {d}s execution for {target:.3f}")
        scheduler.schedule(target, make_callback(d))

    # Wait for the longest task (30s) plus a tiny 1-second buffer for the loop to formally spin back around
    print(f"[Scheduler Test] Entering 31-second await to capture the 30s task...")
    await asyncio.sleep(max(delays) + 1.0) 

    # Verify that all 4 scripts magically found their way to the `events` list via lambda evaluation
    assert len(events) == len(delays), f"Not all callbacks executed! Got {len(events)} expected {len(delays)}"
    
    # Check that they executed extremely close to their target spin-locks
    for delay, actual_time in events:
        expected_time = start_time + delay
        diff = abs(actual_time - expected_time)
        print(f"[Validation] {delay}s test -> Drift: {diff:.5f}s")
        assert diff < 0.05, f"Execution drifted significantly! {delay}s job was off by {diff}s"

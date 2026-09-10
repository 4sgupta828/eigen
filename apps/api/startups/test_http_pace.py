"""Politeness must be per host, not global — a crawl over thousands of hosts should not run at one host's pace."""
import threading
import time

from api.startups.sources import http


def _reset():
    with http._lock:
        http._last_hit.clear()


class TestPacing:
    def test_the_same_host_waits(self):
        _reset()
        http._pace("a.example", 0.30)
        t0 = time.monotonic()
        http._pace("a.example", 0.30)
        assert time.monotonic() - t0 >= 0.25, "a second hit on one host must wait out the gap"

    def test_a_different_host_does_not_wait(self):
        _reset()
        http._pace("a.example", 0.30)
        t0 = time.monotonic()
        http._pace("b.example", 0.30)
        assert time.monotonic() - t0 < 0.10

    def test_one_slow_host_does_not_block_the_others(self):
        """The bug this guards: sleeping while holding the global lock serialised every unrelated host."""
        _reset()
        http._pace("slow.example", 0.40)                      # claim the slow host
        started = threading.Event()
        blocker = threading.Thread(target=lambda: (started.set(), http._pace("slow.example", 0.40)))
        blocker.start()
        started.wait(1.0)
        time.sleep(0.02)                                      # let it enter its wait
        t0 = time.monotonic()
        for i in range(5):
            http._pace(f"fast{i}.example", 0.40)
        elapsed = time.monotonic() - t0
        blocker.join(2.0)
        assert elapsed < 0.15, f"five unrelated hosts took {elapsed:.2f}s behind one waiting host"

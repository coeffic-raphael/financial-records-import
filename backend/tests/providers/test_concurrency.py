"""Bounded extraction concurrency.

The thread pool would happily run dozens of extractions at once. Provider quotas
are counted in requests per minute, so the slowest component has to set the
pace, not the fastest.
"""

import threading
import time

from app.providers.base import ExtractionProvider, ExtractionResult
from app.services.pdf_extraction import get_semaphore, reset_semaphore


class CountingProvider(ExtractionProvider):
    """Records how many extractions overlap in time."""

    name = "counting"

    def __init__(self, hold_seconds: float = 0.05) -> None:
        self._hold = hold_seconds
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self._hold)
        with self._lock:
            self.active -= 1
        return ExtractionResult(records=[])


def test_concurrency_never_exceeds_the_configured_limit():
    reset_semaphore(2)
    provider = CountingProvider()

    def worker():
        with get_semaphore(2):
            provider.extract(b"pdf", "x.pdf")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert provider.peak <= 2, f"{provider.peak} extractions ran at once, limit was 2"
    reset_semaphore()


def test_every_queued_extraction_still_runs():
    """Bounding concurrency must not drop work, only delay it."""
    reset_semaphore(1)
    provider = CountingProvider(hold_seconds=0.01)
    completed = []

    def worker(index: int):
        with get_semaphore(1):
            provider.extract(b"pdf", "x.pdf")
        completed.append(index)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(completed) == [0, 1, 2, 3, 4]
    assert provider.peak == 1
    reset_semaphore()

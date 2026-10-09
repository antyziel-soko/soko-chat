from collections import defaultdict, deque
from time import monotonic


class WindowLimiter:
    """Lekki limiter jednego procesu; w produkcji zastąp współdzielonym backendem."""

    def __init__(self):
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, count: int, window_seconds: int) -> bool:
        now = monotonic()
        bucket = self.events[key]
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if len(bucket) >= count:
            return False
        bucket.append(now)
        return True


login_limiter = WindowLimiter()
message_limiter = WindowLimiter()

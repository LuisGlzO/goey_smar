from contextlib import contextmanager
from time import perf_counter


class MonitorPerformance:
    def __init__(self):
        self.started_at = perf_counter()
        self.data = {
            "stages": [],
            "scraper": [],
            "alerts": [],
        }

    def record(self, group: str, name: str, seconds: float, **details):
        entry = {"name": name, "seconds": round(seconds, 3)}
        entry.update({key: value for key, value in details.items() if value is not None})
        self.data.setdefault(group, []).append(entry)

    @contextmanager
    def stage(self, name: str, group: str = "stages", **details):
        started = perf_counter()
        try:
            yield
        finally:
            self.record(group, name, perf_counter() - started, **details)

    def finish(self):
        self.data["total_seconds"] = round(perf_counter() - self.started_at, 3)
        return self.data

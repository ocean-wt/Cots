"""Process-wide service container (trace writer + live run registry)."""

from app.agents.events import EventBus
from app.services.trace_writer import TraceWriter


class Container:
    def __init__(self) -> None:
        self.trace_writer = TraceWriter()
        self._runs: dict[str, EventBus] = {}

    def register_run(self, run_id: str, bus: EventBus) -> None:
        self._runs[run_id] = bus

    def get_run(self, run_id: str) -> EventBus | None:
        return self._runs.get(run_id)

    def unregister_run(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


container = Container()

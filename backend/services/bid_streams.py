from __future__ import annotations

from collections import defaultdict
from queue import Queue
from threading import RLock
from typing import Any


class BidWorkflowStreams:
    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[str, set[Queue[tuple[str, dict[str, Any]]]]] = defaultdict(set)

    def subscribe(self, workflow_id: str) -> Queue[tuple[str, dict[str, Any]]]:
        subscriber: Queue[tuple[str, dict[str, Any]]] = Queue()
        with self._lock:
            self._subscribers[workflow_id].add(subscriber)
        return subscriber

    def unsubscribe(self, workflow_id: str, subscriber: Queue[tuple[str, dict[str, Any]]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(workflow_id)
            if not subscribers:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(workflow_id, None)

    def publish(self, workflow_id: str, event: str, payload: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(workflow_id, ()))
        for subscriber in subscribers:
            subscriber.put((event, payload))


bid_workflow_streams = BidWorkflowStreams()

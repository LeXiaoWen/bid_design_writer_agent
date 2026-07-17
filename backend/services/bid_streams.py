from __future__ import annotations

from collections import defaultdict
from queue import Empty, Full, Queue
from threading import RLock
from typing import Any


MAX_SUBSCRIBER_EVENTS = 64


class BidWorkflowStreams:
    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[str, set[Queue[tuple[str, dict[str, Any]]]]] = defaultdict(set)

    def subscribe(self, workflow_id: str) -> Queue[tuple[str, dict[str, Any]]]:
        subscriber: Queue[tuple[str, dict[str, Any]]] = Queue(maxsize=MAX_SUBSCRIBER_EVENTS)
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
            try:
                subscriber.put_nowait((event, payload))
            except Full:
                if event == "delta":
                    continue
                self._make_room_for_terminal_event(subscriber)
                try:
                    subscriber.put_nowait((event, payload))
                except Full:
                    continue

    @staticmethod
    def _make_room_for_terminal_event(subscriber: Queue[tuple[str, dict[str, Any]]]) -> None:
        retained = []
        while True:
            try:
                queued_event = subscriber.get_nowait()
            except Empty:
                break
            if queued_event[0] != "delta":
                retained.append(queued_event)
        for queued_event in retained[-(MAX_SUBSCRIBER_EVENTS - 1):]:
            try:
                subscriber.put_nowait(queued_event)
            except Full:
                return


bid_workflow_streams = BidWorkflowStreams()

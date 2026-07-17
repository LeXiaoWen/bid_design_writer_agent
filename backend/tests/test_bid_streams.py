from queue import Empty

from backend.services.bid_streams import MAX_SUBSCRIBER_EVENTS, BidWorkflowStreams


def test_slow_subscriber_queue_is_bounded_and_keeps_terminal_event():
    streams = BidWorkflowStreams()
    subscriber = streams.subscribe("workflow-1")
    streams.publish("workflow-1", "message_start", {"message_id": "message-1"})
    for index in range(MAX_SUBSCRIBER_EVENTS + 10):
        streams.publish("workflow-1", "delta", {"message_id": "message-1", "delta": str(index)})

    assert subscriber.qsize() == MAX_SUBSCRIBER_EVENTS

    streams.publish("workflow-1", "message_done", {"message_id": "message-1", "content": "final"})
    events = []
    while True:
        try:
            events.append(subscriber.get_nowait()[0])
        except Empty:
            break

    assert events == ["message_start", "message_done"]

"""Requests are sent oldest document first and a withdrawn one never, and a
queue that can send no more ends every waiting and every later request with
why.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import threading
import time

import pytest

from docpipe.extraction import scheduler
from docpipe.extraction.throttle import AdaptiveLimit


# -- the queue -----------------------------------------------------------------

def test_the_older_document_is_sent_first_and_a_withdrawn_request_never():
    limit = AdaptiveLimit(start=1, minimum=1, maximum=1)
    queue = scheduler.Scheduler(limit)
    queue.rank(1)                       # document 1 asked first
    queue.rank(2)
    hold = threading.Event()
    sent = []
    blocker = queue.submit(lambda: hold.wait(2), document=9)
    while limit.in_flight == 0:
        time.sleep(0.01)
    ticket = scheduler.Ticket()
    later = queue.submit(lambda: sent.append("doc 2"), document=2)
    gone = queue.submit(lambda: sent.append("withdrawn"), document=1,
                        ticket=ticket)
    first = queue.submit(lambda: sent.append("doc 1"), document=1)
    ticket.withdraw()
    hold.set()
    for future in (blocker, later, first):
        future.result(2)
    with pytest.raises(scheduler.Withdrawn):
        gone.result(2)
    assert sent == ["doc 1", "doc 2"]


def test_a_queue_that_can_send_no_more_ends_every_request_with_why():
    limit = AdaptiveLimit(start=1, minimum=1, maximum=1)
    queue = scheduler.Scheduler(limit)
    assert queue.submit(lambda: "sent", document=1).result(2) == "sent"
    queue._pool.shutdown()
    with pytest.raises(RuntimeError):           # not a wait without end
        queue.submit(lambda: "never", document=1).result(2)
    for _ in range(200):                        # the dispatcher has stopped
        if queue._broken is not None:
            break
        time.sleep(0.01)
    with pytest.raises(RuntimeError):           # and a later request too
        queue.submit(lambda: "never", document=2).result(2)
    assert limit.in_flight == 0

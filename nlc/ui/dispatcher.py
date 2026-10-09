"""
nlc.ui.dispatcher - Thread-safe event dispatcher for worker thread to Tkinter main thread communication
"""

import logging
import queue
from typing import Any, Callable

logger = logging.getLogger(__name__)

class EventDispatcher:
    """Thread-safe queue to marshal background callbacks onto the Tkinter main loop."""
    def __init__(self, root):
        self.root = root
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._poll_delay_ms = 20

    def start(self):
        """Starts the polling loop on the Tkinter root window."""
        self._running = True
        self._schedule_poll()

    def stop(self):
        """Stops the dispatcher polling loop."""
        self._running = False

    def post(self, callback: Callable, *args, **kwargs):
        """Post a callable to be run on the main Tkinter UI thread."""
        self._queue.put((callback, args, kwargs))

    def _schedule_poll(self):
        if not self._running:
            return
        try:
            self.root.after(self._poll_delay_ms, self._process_events)
        except Exception:
            self._running = False

    def _process_events(self):
        # Process up to 50 events per tick to prevent starving UI
        processed = 0
        while not self._queue.empty() and processed < 50:
            try:
                fn, args, kwargs = self._queue.get_nowait()
                fn(*args, **kwargs)
                processed += 1
            except queue.Empty:
                break
            except Exception as e:
                logger.error("Exception in dispatched UI callback: %s", e, exc_info=True)

        if self._running:
            self._schedule_poll()

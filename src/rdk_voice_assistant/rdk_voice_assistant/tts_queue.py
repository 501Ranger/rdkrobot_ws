import queue


class BoundedSpeechQueue:
    """A wrapper for queue.Queue that enforces a max size and provides clean utility methods."""

    def __init__(self, maxsize: int = 5) -> None:
        self._queue: queue.Queue[str] = queue.Queue(maxsize=maxsize)

    def put(self, text: str) -> bool:
        """Attempt to enqueue a text string. Returns True if successful, False if full."""
        try:
            self._queue.put_nowait(text)
            return True
        except queue.Full:
            return False

    def get(self, timeout: float = 0.2) -> str:
        """Get the next item in the queue. Blocks up to timeout. Raises queue.Empty if empty."""
        return self._queue.get(timeout=timeout)

    def clear(self) -> None:
        """Clear all pending items in the queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def qsize(self) -> int:
        """Return current size of the queue."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Return True if the queue is empty."""
        return self._queue.empty()

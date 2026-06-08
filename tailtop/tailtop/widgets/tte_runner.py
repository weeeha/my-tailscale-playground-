"""TTERunner — drives a TTE effect through a Textual Static.

TTE's iterator paces itself (sleeps between frames to hit its target fps),
so we drain it in a worker thread and consume from a queue on the UI loop
via ``set_interval``. Skipping is cheap: cancel the worker, jump to the
optional ``final_text``.
"""

from __future__ import annotations

import queue
import threading
from typing import Iterable

from rich.text import Text
from textual import work
from textual.message import Message
from textual.widgets import Static


class TTERunner(Static):
    """Renders an animated TTE effect inside a Static."""

    DEFAULT_CSS = """
    TTERunner {
        height: auto;
        width: auto;
    }
    """

    class Finished(Message):
        """Posted when the effect completes (naturally or via skip)."""

        def __init__(self, runner: "TTERunner") -> None:
            super().__init__()
            self.runner = runner

    def __init__(
        self,
        effect: Iterable[str],
        *,
        final_text: str | Text | None = None,
        target_fps: int = 60,
        queue_max: int = 256,
        **kwargs,
    ) -> None:
        super().__init__("", **kwargs)
        self._effect = effect
        self._target_fps = target_fps
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=queue_max)
        self._final = final_text
        self._done = False
        self._cancel = threading.Event()
        self._tick_timer = None
        self._last_frame: str | None = None

    def on_mount(self) -> None:
        self._drain_frames()
        self._tick_timer = self.set_interval(1 / self._target_fps, self._tick)

    def on_unmount(self) -> None:
        self._cancel.set()

    def skip(self) -> None:
        """Stop the animation and jump to the final state."""
        if self._done:
            return
        self._cancel.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._render_final()
        self._finish()

    @work(thread=True, exclusive=True, group="tte_drain")
    def _drain_frames(self) -> None:
        try:
            for frame in self._effect:
                if self._cancel.is_set():
                    return
                try:
                    self._queue.put(frame, timeout=2.0)
                except queue.Full:
                    return
        finally:
            try:
                self._queue.put(None, timeout=0.5)
            except queue.Full:
                pass

    def _tick(self) -> None:
        if self._done:
            return
        try:
            frame = self._queue.get_nowait()
        except queue.Empty:
            return
        if frame is None:
            if self._final is not None:
                self._render_final()
            self._finish()
            return
        self._last_frame = frame
        self.update(Text.from_ansi(frame))

    def _render_final(self) -> None:
        if self._final is not None:
            value = self._final if isinstance(self._final, Text) else Text(self._final)
            self.update(value)

    def _finish(self) -> None:
        self._done = True
        if self._tick_timer is not None:
            self._tick_timer.stop()
        self.post_message(self.Finished(self))

    @property
    def done(self) -> bool:
        return self._done

"""
sounds.py — Optional, cross-platform sound feedback.

Sound is a nicety, never a requirement. On Windows we use ``winsound.Beep``
(standard library) on a background thread so the UI never blocks. On other
platforms we fall back to Tk's ``bell()``. Sound can be disabled entirely.

Design notes
------------
* Never raise: any audio failure is swallowed.
* Never block the Tk main loop: Windows beeps run on a daemon thread.
* Respect the user's enabled flag and volume (volume gates whether short
  cosmetic beeps play, since ``winsound.Beep`` has no volume argument).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

_IS_WINDOWS = sys.platform.startswith("win")

if _IS_WINDOWS:
    try:
        import winsound  # type: ignore
    except Exception:  # pragma: no cover
        winsound = None  # type: ignore
else:
    winsound = None  # type: ignore


# Frequency (Hz) / duration (ms) patterns for each event.
_PATTERNS = {
    "click":       [(660, 40)],
    "prepare":     [(440, 80)],
    "go":          [(880, 90)],
    "false_start": [(200, 160), (170, 160)],
    "result":      [(700, 70), (900, 70)],
    "game_over":   [(700, 90), (900, 90), (1100, 140)],
}


class SoundManager:
    """Plays short cosmetic sounds for game events."""

    def __init__(
        self,
        enabled: bool = True,
        volume: float = 0.7,
        bell: Optional[Callable[[], None]] = None,
    ) -> None:
        self.enabled = enabled
        self.volume = volume
        self._bell = bell     # e.g. root.bell, used as a non-Windows fallback

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def play(self, event: str) -> None:
        """Play the sound for *event* (no-op if disabled)."""
        if not self.enabled or self.volume <= 0.0:
            return
        pattern = _PATTERNS.get(event)
        if not pattern:
            return
        if _IS_WINDOWS and winsound is not None:
            threading.Thread(
                target=self._play_windows, args=(pattern,), daemon=True).start()
        elif self._bell is not None:
            # Fallback: a single system bell (can't do custom tones portably).
            try:
                self._bell()
            except Exception:
                pass

    @staticmethod
    def _play_windows(pattern) -> None:
        """Play a beep pattern on Windows (runs on a daemon thread)."""
        try:
            for freq, dur in pattern:
                winsound.Beep(int(freq), int(dur))  # type: ignore
        except Exception:
            pass

    # Convenience wrappers used by the client.
    def click(self) -> None:        self.play("click")
    def prepare(self) -> None:      self.play("prepare")
    def go(self) -> None:           self.play("go")
    def false_start(self) -> None:  self.play("false_start")
    def result(self) -> None:       self.play("result")
    def game_over(self) -> None:    self.play("game_over")

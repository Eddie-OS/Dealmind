"""Rich Console wrapper that never crashes worker threads on Windows.

Windows terminals can occasionally raise ``OSError: [Errno 22] Invalid argument``
or encoding errors while Rich is flushing styled output. Console logging must not
be able to fail a dialogue or batch run, so runtime modules should use this class
instead of ``rich.console.Console`` directly.
"""

from __future__ import annotations

from rich.console import Console


class SafeConsole(Console):
    """A ``Console`` whose common output methods are best-effort only."""

    def print(self, *args, **kwargs):  # noqa: D401, A003
        try:
            return super().print(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return None

    def rule(self, *args, **kwargs):  # noqa: D401
        try:
            return super().rule(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return None

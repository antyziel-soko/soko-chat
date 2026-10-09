from __future__ import annotations

from typing import Any

import httpx
from PySide6.QtCore import QObject, QRunnable, Signal, Slot, Qt


class TaskSignals(QObject):
    finished = Signal(object)


class CallbackRelay(QObject):
    released = Signal(object)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    @Slot(object)
    def deliver(self, result):
        try:
            self.callback(result)
        finally:
            self.released.emit(self)


def start_api_task(pool, owner, task, callback):
    """Keep a main-thread QObject receiver alive until the worker result is handled."""
    if not hasattr(owner, "_task_relays"):
        owner._task_relays = set()
    relay = CallbackRelay(callback)
    owner._task_relays.add(relay)
    relay.released.connect(owner._release_task_relay, Qt.ConnectionType.QueuedConnection)
    task.signals.finished.connect(relay.deliver, Qt.ConnectionType.QueuedConnection)
    pool.start(task)


class ApiTask(QRunnable):
    """Uruchamia pojedyncze żądanie HTTP poza wątkiem interfejsu."""

    def __init__(self, method: str, base_url: str, path: str, token: str | None = None, payload: dict | None = None, params: dict | None = None):
        super().__init__()
        self.method = method
        self.base_url = base_url.rstrip("/")
        self.path = path
        self.token = token
        self.payload = payload
        self.params = params
        self.signals = TaskSignals()

    def run(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = httpx.request(
                self.method,
                f"{self.base_url}{self.path}",
                headers=headers,
                json=self.payload,
                params=self.params,
                timeout=15.0,
            )
            try:
                body: Any = response.json()
            except ValueError:
                body = {"detail": response.text or response.reason_phrase}
            if response.is_error:
                if isinstance(body, dict):
                    message = body.get("detail", "Błąd serwera")
                else:
                    message = "Błąd serwera"
                self.signals.finished.emit({"ok": False, "error": str(message), "status": response.status_code})
            else:
                self.signals.finished.emit({"ok": True, "data": body, "status": response.status_code})
        except httpx.ConnectError:
            self.signals.finished.emit({"ok": False, "error": "Nie można połączyć się z serwerem. Uruchom backend i spróbuj ponownie."})
        except httpx.TimeoutException:
            self.signals.finished.emit({"ok": False, "error": "Serwer nie odpowiedział na czas."})
        except Exception as exc:
            self.signals.finished.emit({"ok": False, "error": f"Błąd połączenia: {exc}"})

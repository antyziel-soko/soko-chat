from __future__ import annotations

import json
import threading
import time

from PySide6.QtCore import QThread, Signal
from websockets.sync.client import connect


class ChannelSocket(QThread):
    received = Signal(dict)
    state_changed = Signal(str)

    def __init__(self, base_url: str, channel_id: str, token: str):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.channel_id = channel_id
        self.token = token
        self.stopping = threading.Event()

    def stop(self):
        self.stopping.set()

    def run(self):
        url = self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url += f"/ws/channels/{self.channel_id}"
        while not self.stopping.is_set():
            try:
                with connect(url, open_timeout=8, close_timeout=2) as socket:
                    socket.send(json.dumps({"type": "authenticate", "token": self.token}))
                    self.state_changed.emit("Połączono z kanałem na żywo")
                    while not self.stopping.is_set():
                        try:
                            raw = socket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        if isinstance(raw, str):
                            try:
                                event = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(event, dict):
                                self.received.emit(event)
            except Exception:
                if not self.stopping.is_set():
                    self.state_changed.emit("Utracono połączenie na żywo — ponawiam…")
                    self.stopping.wait(2)
        self.state_changed.emit("Rozłączono")

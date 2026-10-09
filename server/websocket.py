import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ChannelHub:
    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def connect(self, channel_id: str, websocket: WebSocket):
        async with self.lock:
            self.connections[channel_id].add(websocket)

    async def disconnect(self, channel_id: str, websocket: WebSocket):
        async with self.lock:
            self.connections[channel_id].discard(websocket)
            if not self.connections[channel_id]:
                self.connections.pop(channel_id, None)

    async def broadcast(self, channel_id: str, payload: dict):
        async with self.lock:
            peers = list(self.connections.get(channel_id, ()))
        stale = []
        for peer in peers:
            try:
                await peer.send_json(payload)
            except Exception:
                stale.append(peer)
        for peer in stale:
            await self.disconnect(channel_id, peer)


hub = ChannelHub()

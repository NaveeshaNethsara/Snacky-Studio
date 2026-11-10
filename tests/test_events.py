import asyncio
from types import SimpleNamespace

import pytest

from app.events import TaskEventHub


@pytest.mark.asyncio
async def test_redis_disconnect_keeps_shared_sql_progress_live(monkeypatch):
    class Subscription:
        closed = False
        async def subscribe(self, _): pass
        async def get_message(self, **kwargs): raise ConnectionError('Redis disconnected')
        async def aclose(self): self.closed = True
    subscription = Subscription()
    class Client:
        def pubsub(self): return subscription
        async def aclose(self): pass
    monkeypatch.setattr('redis.asyncio.Redis.from_url', lambda *args, **kwargs: Client())
    class Store:
        calls = 0
        def list(self):
            self.calls += 1
            return [{'id':'one','status':'downloading','updated_at':self.calls}]
    store = Store()
    manager = SimpleNamespace(store=store, owns=lambda _:True)
    hub = TaskEventHub(manager, SimpleNamespace(mode='cloud',redis_url='redis://unused'))
    await hub.start()
    try:
        async def updated():
            while store.calls < 2: await asyncio.sleep(.01)
        await asyncio.wait_for(updated(), 2)
        assert subscription.closed
        assert hub.serial >= 2
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_cloud_stream_closes_after_its_session_expires():
    from app.api import stream_tasks
    class Events:
        async def stream(self, request):
            yield 'data: private tasks\n\n'
    request = SimpleNamespace(cookies={}, app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(mode='cloud',session_secret='s'*32), events=Events())))
    response = await stream_tasks(request)
    assert [event async for event in response.body_iterator] == []

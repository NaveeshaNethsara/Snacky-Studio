"""Tenant-partitioned snapshot reader per API process, shared by SSE clients."""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class TaskEventHub:
    def __init__(self, manager, settings):
        self.manager, self.settings = manager, settings
        self.conditions: dict[str, asyncio.Condition] = {}
        self.snapshots: dict[str, str] = {}
        self.serials: dict[str, int] = {}
        self.task = None

    def _condition(self, tenant_id: str) -> asyncio.Condition:
        if tenant_id not in self.conditions:
            self.conditions[tenant_id] = asyncio.Condition()
        return self.conditions[tenant_id]

    @property
    def condition(self) -> asyncio.Condition:
        return self._condition("default-tenant")

    @property
    def snapshot(self) -> str:
        return self.snapshots.get("default-tenant", "")

    @property
    def serial(self) -> int:
        return self.serials.get("default-tenant", 0)

    async def start(self):
        await self.refresh("default-tenant")
        self.task = asyncio.create_task(self.run())

    async def refresh(self, tenant_id: str = "default-tenant"):
        try:
            if hasattr(self.manager.store, "list"):
                # Handle both local JobStore (no tenant arg) and CloudJobStore (with tenant_id)
                import inspect
                sig = inspect.signature(self.manager.store.list)
                if "tenant_id" in sig.parameters:
                    tasks = await asyncio.to_thread(self.manager.store.list, tenant_id=tenant_id)
                else:
                    tasks = await asyncio.to_thread(self.manager.store.list)
            else:
                tasks = []
        except Exception:
            logger.warning("Could not refresh task snapshot for tenant %s", tenant_id, exc_info=True)
            return

        from app.api import with_ownership
        new_snapshot = json.dumps({"tasks": [with_ownership(self.manager, t) for t in tasks]}, ensure_ascii=False)

        if new_snapshot != self.snapshots.get(tenant_id, ""):
            cond = self._condition(tenant_id)
            async with cond:
                self.snapshots[tenant_id] = new_snapshot
                self.serials[tenant_id] = self.serials.get(tenant_id, 0) + 1
                cond.notify_all()

    async def run(self):
        client, subscription = None, None
        last_reconnect_attempt = 0
        try:
            if self.settings.mode == "cloud":
                try:
                    import redis.asyncio as redis
                    client = redis.Redis.from_url(self.settings.redis_url, socket_connect_timeout=3)
                    subscription = client.pubsub()
                    # Subscribe to global and tenant-specific channels
                    await subscription.psubscribe("snacky:tenant:*")
                    await subscription.subscribe("snacky:tasks")
                except Exception:
                    logger.warning("Redis progress notifications unavailable; using shared SQL snapshots")
                    if subscription:
                        await subscription.aclose()
                    subscription = None
            while True:
                try:
                    tick = asyncio.get_running_loop().time()
                    target_tenant = "default-tenant"
                    if subscription is None and self.settings.mode == "cloud":
                        if tick - last_reconnect_attempt > 15.0:
                            last_reconnect_attempt = tick
                            try:
                                import redis.asyncio as redis
                                if client:
                                    try:
                                        await client.aclose()
                                    except Exception:
                                        pass
                                client = redis.Redis.from_url(self.settings.redis_url, socket_connect_timeout=3)
                                subscription = client.pubsub()
                                await subscription.psubscribe("snacky:tenant:*")
                                await subscription.subscribe("snacky:tasks")
                                logger.info("Successfully reconnected to Redis SSE pub/sub")
                            except Exception:
                                if subscription:
                                    try:
                                        await subscription.aclose()
                                    except Exception:
                                        pass
                                subscription = None

                    if subscription:
                        try:
                            msg = await subscription.get_message(ignore_subscribe_messages=True, timeout=0.5)
                            if msg and msg.get("channel"):
                                ch = msg["channel"].decode() if isinstance(msg["channel"], bytes) else str(msg["channel"])
                                if ch.startswith("snacky:tenant:"):
                                    parts = ch.split(":")
                                    if len(parts) >= 3:
                                        target_tenant = parts[2]
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.warning("Redis progress connection lost; using shared SQL snapshots")
                            try:
                                await subscription.aclose()
                            except Exception:
                                pass
                            subscription = None
                    else:
                        await asyncio.sleep(0.5)

                    await self.refresh(target_tenant)
                    remaining = 0.5 - (asyncio.get_running_loop().time() - tick)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Progress refresh unavailable; retrying")
                    await asyncio.sleep(2)
        finally:
            if subscription:
                await subscription.aclose()
            if client:
                await client.aclose()

    async def stream(self, request, tenant_id: str = "default-tenant"):
        serial = -1
        cond = self._condition(tenant_id)
        while not await request.is_disconnected():
            current_serial = self.serials.get(tenant_id, 0)
            if current_serial != serial:
                serial = current_serial
                snapshot = self.snapshots.get(tenant_id, "")
                yield f"id: {serial}\ndata: {snapshot}\n\n"
            try:
                async with cond:
                    await asyncio.wait_for(cond.wait_for(lambda: self.serials.get(tenant_id, 0) != serial), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

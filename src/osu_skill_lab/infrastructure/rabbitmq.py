"""Persistent, confirmed notifications; PostgreSQL remains the job authority."""

from types import TracebackType
from typing import Self

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractIncomingMessage, AbstractQueue
from pydantic import BaseModel, ConfigDict, Field


class JobMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(default=1, ge=1, le=1)
    item_id: int = Field(gt=0, le=2**63 - 1)


class RabbitBroker:
    def __init__(self, url: str, *, queue_name: str = "osu.analysis-items.v1") -> None:
        self._url, self.queue_name = url, queue_name
        self.connection: AbstractConnection
        self.channel: AbstractChannel
        self.queue: AbstractQueue

    async def __aenter__(self) -> Self:
        self.connection = await aio_pika.connect(self._url, timeout=5)
        try:
            self.channel = await self.connection.channel(
                publisher_confirms=True, on_return_raises=True
            )
            await self.channel.set_qos(prefetch_count=1)
            self.queue = await self.channel.declare_queue(
                self.queue_name,
                durable=True,
                arguments={"x-max-length": 2000, "x-overflow": "reject-publish"},
                timeout=5,
            )
        except BaseException:
            await self.connection.close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.connection.close()

    async def publish(self, item_id: int) -> None:
        body = JobMessage(item_id=item_id).model_dump_json().encode()
        confirmation = await self.channel.default_exchange.publish(
            aio_pika.Message(
                body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=self.queue_name,
            mandatory=True,
            timeout=5,
        )
        if confirmation is None:
            raise RuntimeError("Publisher confirmation missing")

    async def receive(self) -> AbstractIncomingMessage | None:
        return await self.queue.get(fail=False, timeout=5)

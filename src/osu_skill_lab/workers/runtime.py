"""Bounded execution of independent per-map jobs on one worker instance."""

import asyncio
from collections.abc import Awaitable, Callable

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from osu_skill_lab.infrastructure.rabbitmq import JobMessage, RabbitBroker


class WorkerRestartRequired(RuntimeError):
    pass


async def consume_jobs(
    broker: RabbitBroker,
    process: Callable[[int], Awaitable[None]],
    *,
    concurrency: int = 1,
) -> None:
    if not 1 <= concurrency <= 32:
        raise ValueError("Worker concurrency must be between 1 and 32")
    slots = asyncio.Semaphore(concurrency)

    async def handle(message: AbstractIncomingMessage) -> None:
        try:
            try:
                if len(message.body) > 256:
                    raise ValueError("Oversized message")
                envelope = JobMessage.model_validate_json(message.body)
            except (ValidationError, ValueError):
                await message.reject(requeue=False)
                return
            await process(envelope.item_id)
            await message.ack()
        finally:
            slots.release()

    try:
        # On failure/cancellation, finish cancelling active handlers before closing
        # the iterator/channel. Unacked deliveries remain available for redelivery.
        async with broker.queue.iterator() as iterator, asyncio.TaskGroup() as tasks:
            while True:
                await slots.acquire()
                try:
                    message = await anext(iterator)
                except StopAsyncIteration:
                    slots.release()
                    break
                except BaseException:
                    slots.release()
                    raise
                tasks.create_task(handle(message))
    except BaseExceptionGroup as errors:
        restart, _ = errors.split(WorkerRestartRequired)
        if restart is not None:
            raise WorkerRestartRequired("Worker CPU process unavailable") from None
        raise

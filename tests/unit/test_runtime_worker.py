import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from aio_pika.abc import AbstractIncomingMessage
from pydantic import SecretStr

from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.rabbitmq import JobMessage, RabbitBroker
from osu_skill_lab.workers import __main__ as entrypoint
from osu_skill_lab.workers.runtime import WorkerRestartRequired, consume_jobs


class Message:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.ack = AsyncMock()
        self.reject = AsyncMock()


class Queue:
    def __init__(self, messages: list[Message], *, remain_open: bool = False) -> None:
        self.messages, self.remain_open = messages, remain_open

    @asynccontextmanager
    async def iterator(self) -> AsyncIterator[AsyncIterator[AbstractIncomingMessage]]:
        async def values() -> AsyncIterator[AbstractIncomingMessage]:
            for message in self.messages:
                yield cast(AbstractIncomingMessage, message)
            if self.remain_open:
                await asyncio.Event().wait()

        yield values()


def broker_for(messages: list[Message], *, remain_open: bool = False) -> RabbitBroker:
    broker = Mock(spec=RabbitBroker)
    broker.queue = Queue(messages, remain_open=remain_open)
    return cast(RabbitBroker, broker)


@pytest.mark.parametrize("capacity", [1, 3])
async def test_runtime_processes_up_to_capacity_and_acks_only_after_work(capacity: int) -> None:
    messages = [
        Message(JobMessage(item_id=item).model_dump_json().encode()) for item in range(1, 7)
    ]
    entered: list[int] = []
    active = peak = 0
    full, release = asyncio.Event(), asyncio.Event()

    async def process(item_id: int) -> None:
        nonlocal active, peak
        entered.append(item_id)
        active += 1
        peak = max(active, peak)
        if len(entered) == capacity:
            full.set()
        try:
            await release.wait()
        finally:
            active -= 1

    task = asyncio.create_task(consume_jobs(broker_for(messages), process, concurrency=capacity))
    try:
        async with asyncio.timeout(2):
            await full.wait()
            await asyncio.sleep(0)
            assert len(entered) == capacity
            assert all(message.ack.await_count == 0 for message in messages)
            release.set()
            await task
        assert peak == capacity and sorted(entered) == list(range(1, 7))
        assert all(message.ack.await_count == 1 for message in messages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "body", [b"{}", b'{"item_id":true}', b'{"item_id":1,"version":2}', b"x" * 257]
)
async def test_poison_messages_are_rejected_without_running_job(body: bytes) -> None:
    message = Message(body)
    process = AsyncMock()
    await consume_jobs(broker_for([message]), process)
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_called()
    process.assert_not_called()


async def test_fatal_error_interrupts_idle_receive_and_cancels_sibling_without_ack() -> None:
    messages = [Message(JobMessage(item_id=item).model_dump_json().encode()) for item in (1, 2)]
    both_started, cancelled = asyncio.Event(), asyncio.Event()

    async def process(item_id: int) -> None:
        if item_id == 1:
            await both_started.wait()
            raise WorkerRestartRequired("Restart")
        both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with asyncio.timeout(2):
        with pytest.raises(WorkerRestartRequired):
            await consume_jobs(broker_for(messages, remain_open=True), process, concurrency=3)
    assert cancelled.is_set()
    assert all(message.ack.await_count == 0 for message in messages)


async def test_shutdown_cancels_active_jobs_without_ack() -> None:
    messages = [Message(JobMessage(item_id=1).model_dump_json().encode())]
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def process(item_id: int) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(consume_jobs(broker_for(messages, remain_open=True), process))
    async with asyncio.timeout(2):
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cancelled.is_set() and messages[0].ack.await_count == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["worker", "--concurrency", "0"],
        ["worker", "--concurrency", "33"],
        ["dispatcher", "--concurrency", "2"],
    ],
)
def test_bad_capacity_cli_is_rejected_before_startup(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", *arguments])
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("configured", "override", "expected"), [(1, None, 1), (3, None, 3), (1, 4, 4)]
)
async def test_worker_wires_one_capacity_to_pool_importer_and_consumer(
    configured: int,
    override: int | None,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://x@localhost/test"),
        worker_concurrency=configured,
    )
    database, mirror = Mock(), Mock()
    database.close, mirror.close = AsyncMock(), AsyncMock()
    executor = Mock()
    pool_factory = Mock(return_value=executor)
    worker = Mock()
    worker.serve = AsyncMock()
    worker_factory = Mock(return_value=worker)
    importer_factory = Mock()
    service_factory = Mock()
    monkeypatch.setattr(entrypoint, "Settings", lambda: settings)
    monkeypatch.setattr(entrypoint, "Database", lambda _: database)
    monkeypatch.setattr(entrypoint, "HinamizawaClient", lambda **_: mirror)
    monkeypatch.setattr(entrypoint, "ProcessPoolExecutor", pool_factory)
    monkeypatch.setattr(entrypoint, "AnalysisService", service_factory)
    monkeypatch.setattr(entrypoint, "MirrorImportService", importer_factory)
    monkeypatch.setattr(entrypoint, "ImportWorker", worker_factory)
    await entrypoint.run("worker", concurrency=override)
    pool_factory.assert_called_once_with(max_workers=expected)
    service_factory.assert_called_once_with(database, executor, max_in_flight=expected)
    assert importer_factory.call_args.kwargs["max_concurrent"] == expected
    assert importer_factory.call_args.kwargs["max_in_flight"] == expected
    worker.serve.assert_awaited_once_with(
        settings.rabbitmq_url.get_secret_value(), concurrency=expected
    )
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
    mirror.close.assert_awaited_once()
    database.close.assert_awaited_once()

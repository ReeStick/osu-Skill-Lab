import argparse
import asyncio
import logging
import signal
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress

from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.service import AnalysisService
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.hinamizawa import HinamizawaClient
from osu_skill_lab.infrastructure.provider_budget import PostgresMirrorBudget
from osu_skill_lab.workers.dispatcher import serve as dispatch
from osu_skill_lab.workers.import_worker import ImportWorker, WorkerRestartRequired


async def run(role: str) -> None:
    settings = Settings()
    database = Database(settings)
    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    with suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        if role == "dispatcher":
            await dispatch(database, settings.rabbitmq_url.get_secret_value())
        else:
            executor = ProcessPoolExecutor(max_workers=1)
            mirror = HinamizawaClient(
                timeout=settings.mirror_timeout_seconds,
                cache_ttl=settings.mirror_cache_ttl_seconds,
                budget=PostgresMirrorBudget(database),
            )
            try:
                service = AnalysisService(database, executor, max_in_flight=1)
                importer = MirrorImportService(
                    mirror, service, official_cache_ttl=settings.osu_cache_ttl_seconds
                )
                await ImportWorker(database, importer).serve(
                    settings.rabbitmq_url.get_secret_value()
                )
            finally:
                try:
                    await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
                finally:
                    await mirror.close()
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["dispatcher", "worker"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # Transport logs can contain connection URLs. Application logs use exception types only.
    for name in ("aio_pika", "aiormq"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    with suppress(KeyboardInterrupt, asyncio.CancelledError):
        try:
            asyncio.run(run(args.role))
        except WorkerRestartRequired:
            logging.getLogger(__name__).error("Worker CPU process unavailable; restart required")
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()

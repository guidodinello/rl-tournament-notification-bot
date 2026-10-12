import asyncio
import contextlib
import signal

from telegram.ext import ApplicationBuilder, ContextTypes

from rltournamentbot.bot import BotData, _poll_task, build_application
from rltournamentbot.config import Config, load_config
from rltournamentbot.logger import get_logger, init_logging


async def main_async(config: Config) -> None:
    logger = get_logger(__name__)
    logger.info("Starting RLCS Tournament Notification Bot")

    app = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .context_types(ContextTypes(bot_data=BotData))
        .build()
    )

    build_application(config, app)

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_run_polling(app)),
                tg.create_task(_poll_task(app, config)),
            ]

            loop = asyncio.get_running_loop()

            def _shutdown() -> None:
                # Cancelling every sibling task here raises CancelledError inside each --
                # TaskGroup excludes that from the ExceptionGroup below, so a
                # signal-triggered shutdown exits main_async cleanly. A genuine subsystem
                # failure (e.g. app.start()/get_me()/delete_webhook failing during
                # bootstrap, or PTB's getUpdates loop giving up -- see _run_polling) is a
                # real exception, which TaskGroup turns into cross-cancellation of the
                # siblings and an ExceptionGroup -- no manual handling needed for that
                # case either.
                logger.info("Shutdown signal received, stopping...")
                for t in tasks:
                    t.cancel()

            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, _shutdown)
    except* Exception as eg:
        # Previously this used asyncio.gather(..., return_exceptions=True) and never
        # inspected the results -- a crash here went completely unlogged while the sibling
        # task kept running, leaving the bot looking alive but silently unresponsive.
        logger.error("Essential subsystem failed -- shutting down", exc_info=eg)
        raise


_POLLING_TASK_NAME = "Updater:start_polling:polling_task"


class PollingStoppedError(RuntimeError):
    """PTB's getUpdates loop ended on its own while the bot was meant to be running."""


def _find_polling_task() -> asyncio.Task:
    # PTB runs getUpdates in a background task it never exposes publicly, but it
    # gives it a stable name. Without a handle on it, nothing notices when it dies.
    for task in asyncio.all_tasks():
        if task.get_name() == _POLLING_TASK_NAME:
            return task
    raise RuntimeError(f"Could not find PTB polling task {_POLLING_TASK_NAME!r}")


async def _run_polling(app) -> None:
    async with app:
        await app.updater.start_polling()
        try:
            await app.start()
            # Wait on the getUpdates loop itself rather than forever. PTB retries most
            # errors indefinitely, but aborts the loop on InvalidToken -- which Telegram
            # also triggers with a transient 401/404 -- and nothing else awaits that
            # task. The process then stayed up (the Liquipedia poll kept running) while
            # never receiving another command. Raising here lets TaskGroup tear down and
            # exit, so Docker's restart policy brings the bot back.
            polling_task = _find_polling_task()
            # asyncio.wait neither raises the task's error nor cancels it when we're
            # cancelled for shutdown -- updater.stop() below winds it down then.
            await asyncio.wait({polling_task})
            exc = None if polling_task.cancelled() else polling_task.exception()
            raise PollingStoppedError("Telegram polling stopped unexpectedly") from exc
        finally:
            if app.updater.running:
                try:
                    # Re-raises the polling task's error if it died; it's already been
                    # chained onto PollingStoppedError, so don't let it mask that.
                    await app.updater.stop()
                except Exception:
                    get_logger(__name__).exception("Error while stopping Telegram updater")
            if app.running:
                await app.stop()


def main() -> None:
    config = load_config()
    init_logging(file=config.logger.file, level=config.logger.level)
    asyncio.run(main_async(config))


if __name__ == "__main__":
    main()

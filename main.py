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
                # failure (e.g. a Telegram "Conflict: terminated by other getUpdates
                # request" right after a redeploy) is a real exception, which TaskGroup
                # turns into cross-cancellation of the siblings and an ExceptionGroup --
                # no manual handling needed for that case either.
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


async def _run_polling(app) -> None:
    async with app:
        await app.updater.start_polling()
        await app.start()
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()


def main() -> None:
    config = load_config()
    init_logging(file=config.logger.file, level=config.logger.level)
    asyncio.run(main_async(config))


if __name__ == "__main__":
    main()

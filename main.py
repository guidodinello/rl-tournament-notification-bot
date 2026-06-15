import asyncio
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

    tasks = [asyncio.create_task(_run_polling(app))]
    tasks.append(asyncio.create_task(_poll_task(app, config)))

    loop = asyncio.get_running_loop()

    def _shutdown():
        logger.info("Shutdown signal received, stopping...")
        for t in tasks:
            t.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await asyncio.gather(*tasks, return_exceptions=True)


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

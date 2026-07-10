"""
Точка входа: запускает Telegram-бота и веб-сервер одновременно.
Railway вызывает: python main.py
"""
import asyncio
import logging
import os

import uvicorn

from db import init_db

log = logging.getLogger("main")


async def start_bot():
    from bot import bot, dp
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


async def start_web():
    port = int(os.environ.get("PORT", 8080))
    config = uvicorn.Config("web:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    init_db()
    log.info("Запуск бота + веб-сервера...")

    await asyncio.gather(
        start_bot(),
        start_web(),
    )


if __name__ == "__main__":
    asyncio.run(main())

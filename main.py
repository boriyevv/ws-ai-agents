"""WS-Tizim: ishga tushirish.  Buyruq:  python main.py"""
import asyncio
import logging
import sys

if sys.platform == "win32":
    # psycopg (async) Windows'da SelectorEventLoop talab qiladi
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)   # har daqiqalik jadval yozuvlari shovqin qilmasin

from app.bot import build_app  # noqa: E402

if __name__ == "__main__":
    build_app().run_polling(drop_pending_updates=True)

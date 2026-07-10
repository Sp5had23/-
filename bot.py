import os
import json
import logging
import asyncio
from datetime import date, datetime
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from db import init_db, add_expense, get_today, get_month, get_all, get_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("expense-bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_allowed_raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {
    int(x) for x in _allowed_raw.split(",") if x.strip().isdigit()
} if _allowed_raw else None

for var_name in ("TELEGRAM_BOT_TOKEN", "GROQ_API_KEY"):
    if not os.environ.get(var_name, "").strip():
        raise RuntimeError(f"Не задана переменная окружения: {var_name}")

# ---------------------------------------------------------------------------
# LLM-парсер трат
# ---------------------------------------------------------------------------
EXPENSE_SYSTEM_PROMPT = """\
Ты парсер трат. Пользователь пишет о покупках/тратах (русский/украинский).

Извлеки ВСЕ траты и верни СТРОГО JSON (без markdown, без пояснений):

{"expenses": [{"amount": 10.0, "currency": "EUR", "description": "Посылка"}]}

Правила:
- Валюта по умолчанию EUR. € -> EUR, $ -> USD, грн -> UAH. ISO-код.
- Число может быть до или после описания: "10 посылка", "рис 2", "1.70 энергетик".
- "2.Рис" или "2 рис" — сумма 2, описание "Рис".
- Нет трат -> {"expenses": []}.
- description: коротко, с большой буквы, на языке сообщения.
- amount: положительное число (float).
- ТОЛЬКО валидный JSON.
"""


async def parse_expenses(text: str) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": EXPENSE_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GROQ_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        log.error("Groq error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Groq API: {resp.status_code}")

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)
    clean = []
    for exp in parsed.get("expenses", []):
        try:
            clean.append({
                "amount": float(exp["amount"]),
                "currency": str(exp.get("currency", "EUR")).upper(),
                "description": str(exp.get("description", "")).strip() or "Расход",
            })
        except (KeyError, ValueError, TypeError):
            continue
    return clean


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------
def format_expenses(rows: list[dict], title: str) -> str:
    if not rows:
        return f"📊 {title}\n\nПока пусто."

    totals = get_summary(rows)
    lines = [f"📊 {title}", ""]
    for cur, total in totals.items():
        lines.append(f"💰 Итого: {total:.2f} {cur}")
    lines.append(f"🧾 Записей: {len(rows)}")
    lines.append("")

    show = rows[-15:] if len(rows) > 15 else rows
    for r in show:
        lines.append(f"• {r['date']} {r['time']} — {r['amount']:.2f} {r['currency']} — {r['description']}")
    if len(rows) > 15:
        lines.append(f"… и ещё {len(rows) - 15}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram-бот
# ---------------------------------------------------------------------------
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


def is_allowed(uid: int) -> bool:
    return ALLOWED_USER_IDS is None or uid in ALLOWED_USER_IDS


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return await message.answer("⛔ Нет доступа.")
    await message.answer(
        "👋 Привет! Я считаю твои траты.\n\n"
        "Просто напиши, например:\n"
        "  <code>10 забрал посылку</code>\n"
        "или списком:\n"
        "  <code>2 рис\n3 чипсы\n1.70 энергетик</code>\n\n"
        "/today — за сегодня\n"
        "/month — за месяц\n"
        "/all — все траты",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    await cmd_start(message)


@dp.message(Command("today"))
async def cmd_today(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    rows = get_today()
    await message.answer(format_expenses(rows, f"Сегодня ({date.today().isoformat()})"))


@dp.message(Command("month"))
async def cmd_month(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    rows = get_month()
    await message.answer(format_expenses(rows, f"Месяц ({datetime.now().strftime('%Y-%m')})"))


@dp.message(Command("all"))
async def cmd_all(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    rows = get_all()
    await message.answer(format_expenses(rows, "Все траты"))


@dp.message(F.text)
async def handle_expense(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return await message.answer("⛔ Нет доступа.")

    text = message.text.strip()
    if not text:
        return

    msg = await message.answer("⏳ Разбираю…")

    try:
        expenses = await parse_expenses(text)
    except Exception as e:
        log.exception("Ошибка LLM")
        return await msg.edit_text(f"❌ Ошибка: {e}")

    if not expenses:
        return await msg.edit_text(
            "🤔 Не нашёл трат. Пример: <code>10 забрал посылку</code>",
            parse_mode="HTML",
        )

    for exp in expenses:
        add_expense(exp["amount"], exp["currency"], exp["description"])

    lines = ["✅ Записал:"]
    total_by_cur: dict[str, float] = {}
    for exp in expenses:
        lines.append(f"• {exp['amount']:.2f} {exp['currency']} — {exp['description']}")
        total_by_cur[exp["currency"]] = total_by_cur.get(exp["currency"], 0) + exp["amount"]

    if len(expenses) > 1:
        lines.append("")
        for cur, total in total_by_cur.items():
            lines.append(f"Сумма: {total:.2f} {cur}")

    await msg.edit_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
async def main() -> None:
    init_db()
    log.info("Бот запущен. Пользователи: %s", ALLOWED_USER_IDS or "все")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

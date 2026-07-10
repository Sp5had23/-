"""
Expense Tracker Telegram Bot
=============================
Принимает сообщения о тратах на естественном языке (в т.ч. списком),
парсит их через Gemini API и записывает в Google Таблицу
(через Apps Script Web App вместо Service Account — так проще).

Примеры сообщений, которые понимает бот:
    10 забрал посылку
    2 рис
    3 чипсы
    1.70 энергетик
    Купил в магазине: рис 2, чипсы 3, энергетик 1.70€

Команды:
    /start  - приветствие и проверка настроек
    /today  - траты за сегодня
    /month  - траты за текущий месяц
    /all    - все траты и общая сумма
    /help   - помощь

Переменные окружения (задаются в Railway -> Variables):
    TELEGRAM_BOT_TOKEN   - токен бота от @BotFather
    GEMINI_API_KEY       - ключ Gemini API (https://aistudio.google.com/apikey)
    SHEETS_WEBAPP_URL    - URL опубликованного Apps Script Web App
    ALLOWED_USER_IDS     - (опционально) через запятую, кто может писать боту.
                            Если не задано - отвечает всем.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, date
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

# --------------------------------------------------------------------------
# Настройка логирования
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("expense-bot")

# --------------------------------------------------------------------------
# Переменные окружения
# --------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "").strip()
_allowed_raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {
    int(x) for x in _allowed_raw.split(",") if x.strip().isdigit()
} if _allowed_raw else None  # None = разрешено всем

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

REQUIRED_VARS = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "SHEETS_WEBAPP_URL": SHEETS_WEBAPP_URL,
}
missing = [k for k, v in REQUIRED_VARS.items() if not v]
if missing:
    raise RuntimeError(
        f"Не заданы обязательные переменные окружения: {', '.join(missing)}. "
        f"Задай их в Railway -> Variables."
    )

# --------------------------------------------------------------------------
# Промпт для Gemini: превращаем свободный текст в список трат JSON-ом
# --------------------------------------------------------------------------
GEMINI_SYSTEM_PROMPT = """\
Ты парсер трат для бота учёта финансов. Пользователь пишет сообщение о \
покупках/тратах на любом языке (обычно русский или украинский), иногда \
одной строкой, иногда списком в несколько строк.

Твоя задача: извлечь ВСЕ отдельные траты из сообщения и вернуть СТРОГО JSON \
без каких-либо пояснений, преамбул или markdown-разметки (без ```), в формате:

{
  "expenses": [
    {"amount": 10.0, "currency": "EUR", "description": "забрал посылку"},
    {"amount": 2.0, "currency": "EUR", "description": "рис"}
  ]
}

Правила:
- Если валюта не указана явно (нет €, $, грн, руб и т.п.) — считай валюту EUR.
- Если явно указан символ или код валюты, определи её: € -> EUR, $ -> USD, \
грн/uah -> UAH, руб/rub -> RUB, и т.д. Используй трёхбуквенный ISO-код.
- Число может стоять до или после описания ("10 посылка" или "рис 2" или \
"1.70 энергетик"). Разделитель дробной части может быть точкой или запятой.
- Если строка вида "2.Рис" или "2. Рис" — это "2" это количество/цена, \
а "Рис" описание (число может быть просто ценой товара, не количеством — \
трактуй его как сумму траты в валюте по умолчанию, если нет иных признаков \
количества и цены за штуку).
- Если в сообщении нет ни одной распознаваемой траты (это не про деньги), \
верни {"expenses": []}.
- description пиши коротко, с большой буквы, без лишних слов, на языке \
исходного сообщения.
- amount всегда положительное число (float).
- Верни ТОЛЬКО валидный JSON, ничего больше.
"""


async def parse_expenses_with_gemini(text: str) -> list[dict[str, Any]]:
    """Отправляет текст в Gemini и возвращает список распарсенных трат."""
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GEMINI_URL, json=payload)

    if resp.status_code != 200:
        log.error("Gemini API error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Ошибка Gemini API: {resp.status_code}")

    data = resp.json()
    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        log.error("Неожиданный формат ответа Gemini: %s", data)
        raise RuntimeError("Не удалось разобрать ответ Gemini") from e

    raw_text = raw_text.strip()
    # На всякий случай снимаем возможные markdown-обёртки
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.error("Gemini вернул невалидный JSON: %s", raw_text)
        raise RuntimeError("Gemini вернул невалидный JSON") from e

    expenses = parsed.get("expenses", [])
    # Валидация базовых полей
    clean = []
    for exp in expenses:
        try:
            amount = float(exp["amount"])
            currency = str(exp.get("currency", "EUR")).upper()
            description = str(exp.get("description", "")).strip() or "Без описания"
            clean.append({
                "amount": amount,
                "currency": currency,
                "description": description,
            })
        except (KeyError, ValueError, TypeError):
            log.warning("Пропущена некорректная запись от Gemini: %s", exp)
            continue

    return clean


# --------------------------------------------------------------------------
# Работа с Google Sheets через Apps Script Web App
# --------------------------------------------------------------------------
async def sheets_append(expenses: list[dict[str, Any]]) -> None:
    """Добавляет строки трат в Google Таблицу."""
    now = datetime.now()
    rows = [
        {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "amount": exp["amount"],
            "currency": exp["currency"],
            "description": exp["description"],
        }
        for exp in expenses
    ]
    payload = {"action": "append", "rows": rows}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.post(SHEETS_WEBAPP_URL, json=payload)

    if resp.status_code != 200:
        log.error("Sheets webapp error %s: %s", resp.status_code, resp.text)
        raise RuntimeError("Не удалось записать в Google Таблицу")

    try:
        result = resp.json()
    except json.JSONDecodeError:
        log.error("Sheets webapp вернул не-JSON: %s", resp.text)
        raise RuntimeError("Google Таблица вернула неожиданный ответ")

    if not result.get("ok"):
        log.error("Sheets webapp вернул ошибку: %s", result)
        raise RuntimeError(result.get("error", "Неизвестная ошибка Google Таблицы"))


async def sheets_summary(period: str) -> dict[str, Any]:
    """Запрашивает у Apps Script сводку за период: today / month / all."""
    payload = {"action": "summary", "period": period}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.post(SHEETS_WEBAPP_URL, json=payload)

    if resp.status_code != 200:
        log.error("Sheets webapp error %s: %s", resp.status_code, resp.text)
        raise RuntimeError("Не удалось получить данные из Google Таблицы")

    try:
        result = resp.json()
    except json.JSONDecodeError:
        log.error("Sheets webapp вернул не-JSON: %s", resp.text)
        raise RuntimeError("Google Таблица вернула неожиданный ответ")

    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Неизвестная ошибка Google Таблицы"))

    return result


def format_summary(result: dict[str, Any], title: str) -> str:
    totals = result.get("totals", {})
    count = result.get("count", 0)
    items = result.get("items", [])

    if count == 0:
        return f"📊 {title}\n\nПока нет ни одной записи."

    lines = [f"📊 {title}", ""]
    for currency, amount in totals.items():
        lines.append(f"💰 Итого: {amount:.2f} {currency}")
    lines.append(f"🧾 Записей: {count}")

    # Показываем последние записи (не более 15), чтобы не спамить
    if items:
        lines.append("")
        lines.append("Последние записи:")
        for item in items[-15:]:
            lines.append(
                f"• {item['date']} — {item['amount']:.2f} {item['currency']} "
                f"— {item['description']}"
            )
        if len(items) > 15:
            lines.append(f"… и ещё {len(items) - 15}")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Telegram-бот
# --------------------------------------------------------------------------
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


def is_allowed(user_id: int) -> bool:
    return ALLOWED_USER_IDS is None or user_id in ALLOWED_USER_IDS


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к этому боту.")
        return
    await message.answer(
        "👋 Привет! Я считаю твои траты.\n\n"
        "Просто напиши сообщение о покупке, например:\n"
        "  <code>10 забрал посылку</code>\n"
        "или списком:\n"
        "  <code>2 рис\n3 чипсы\n1.70 энергетик</code>\n\n"
        "Команды:\n"
        "/today — траты за сегодня\n"
        "/month — траты за текущий месяц\n"
        "/all — все траты\n"
        "/help — помощь",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    await message.answer(
        "Просто пиши траты обычным текстом, я сам пойму сумму, валюту и "
        "описание с помощью Gemini и запишу в Google Таблицу с датой.\n\n"
        "/today — сводка за сегодня\n"
        "/month — сводка за месяц\n"
        "/all — сводка за всё время"
    )


@dp.message(Command("today"))
async def cmd_today(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    msg = await message.answer("⏳ Считаю…")
    try:
        result = await sheets_summary("today")
        text = format_summary(result, f"Траты за сегодня ({date.today().isoformat()})")
        await msg.edit_text(text)
    except Exception as e:
        log.exception("Ошибка /today")
        await msg.edit_text(f"❌ Ошибка: {e}")


@dp.message(Command("month"))
async def cmd_month(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    msg = await message.answer("⏳ Считаю…")
    try:
        result = await sheets_summary("month")
        month_name = datetime.now().strftime("%Y-%m")
        text = format_summary(result, f"Траты за месяц ({month_name})")
        await msg.edit_text(text)
    except Exception as e:
        log.exception("Ошибка /month")
        await msg.edit_text(f"❌ Ошибка: {e}")


@dp.message(Command("all"))
async def cmd_all(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        return
    msg = await message.answer("⏳ Считаю…")
    try:
        result = await sheets_summary("all")
        text = format_summary(result, "Все траты")
        await msg.edit_text(text)
    except Exception as e:
        log.exception("Ошибка /all")
        await msg.edit_text(f"❌ Ошибка: {e}")


@dp.message(F.text)
async def handle_expense_message(message: Message) -> None:
    if not is_allowed(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к этому боту.")
        return

    text = message.text.strip()
    if not text:
        return

    thinking_msg = await message.answer("⏳ Разбираю…")

    try:
        expenses = await parse_expenses_with_gemini(text)
    except Exception as e:
        log.exception("Ошибка парсинга Gemini")
        await thinking_msg.edit_text(f"❌ Не смог разобрать сообщение: {e}")
        return

    if not expenses:
        await thinking_msg.edit_text(
            "🤔 Не нашёл в сообщении трат. Попробуй написать конкретнее, "
            "например: <code>10 забрал посылку</code>",
            parse_mode="HTML",
        )
        return

    try:
        await sheets_append(expenses)
    except Exception as e:
        log.exception("Ошибка записи в Google Sheets")
        await thinking_msg.edit_text(f"❌ Не смог записать в таблицу: {e}")
        return

    lines = ["✅ Записал:"]
    total_by_currency: dict[str, float] = {}
    for exp in expenses:
        lines.append(f"• {exp['amount']:.2f} {exp['currency']} — {exp['description']}")
        total_by_currency[exp["currency"]] = (
            total_by_currency.get(exp["currency"], 0) + exp["amount"]
        )

    if len(expenses) > 1:
        lines.append("")
        for currency, total in total_by_currency.items():
            lines.append(f"Сумма: {total:.2f} {currency}")

    await thinking_msg.edit_text("\n".join(lines))


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------
async def main() -> None:
    log.info("Бот запускается…")
    log.info("Разрешённые пользователи: %s", ALLOWED_USER_IDS or "все")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

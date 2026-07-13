import sqlite3
from pathlib import Path
from datetime import datetime, date

DB_PATH = Path("expenses.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                time      TEXT NOT NULL,
                amount    REAL NOT NULL,
                currency  TEXT NOT NULL DEFAULT 'EUR',
                description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def add_expense(amount: float, currency: str, description: str) -> int:
    now = datetime.now()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (date, time, amount, currency, description) VALUES (?, ?, ?, ?, ?)",
            (now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), amount, currency, description),
        )
        return cur.lastrowid


def get_today() -> list[dict]:
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE date = ? ORDER BY id", (today,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_month() -> list[dict]:
    prefix = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE date LIKE ? ORDER BY id", (prefix + "%",)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM expenses ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_by_date(day: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE date = ? ORDER BY id", (day,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_daily_totals(year: int, month: int) -> dict[str, float]:
    """Суммы по дням за указанный месяц: {"2026-07-10": 15.50, ...}"""
    prefix = f"{year:04d}-{month:02d}"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, SUM(amount) as total FROM expenses WHERE date LIKE ? GROUP BY date",
            (prefix + "%",),
        ).fetchall()
    return {r["date"]: round(r["total"], 2) for r in rows}


def get_summary(rows: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for r in rows:
        totals[r["currency"]] = totals.get(r["currency"], 0) + r["amount"]
    return {k: round(v, 2) for k, v in totals.items()}

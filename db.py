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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS routine_checks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
                date       TEXT NOT NULL,
                UNIQUE(routine_id, date)
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


# ---------------------------------------------------------------------------
# Рутины
# ---------------------------------------------------------------------------
def add_routine(name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO routines (name) VALUES (?)", (name,))
        return cur.lastrowid


def delete_routine(routine_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM routine_checks WHERE routine_id = ?", (routine_id,))
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))


def get_routines() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM routines WHERE active = 1 ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def toggle_routine_check(routine_id: int, day: str) -> bool:
    """Переключает чек: если был — убирает, если нет — ставит. Возвращает новое состояние."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM routine_checks WHERE routine_id = ? AND date = ?",
            (routine_id, day),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM routine_checks WHERE id = ?", (existing["id"],))
            return False
        else:
            conn.execute(
                "INSERT INTO routine_checks (routine_id, date) VALUES (?, ?)",
                (routine_id, day),
            )
            return True


def get_checks_for_period(start_date: str, end_date: str) -> dict[int, set[str]]:
    """Возвращает {routine_id: {date1, date2, ...}} за период."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT routine_id, date FROM routine_checks WHERE date >= ? AND date <= ?",
            (start_date, end_date),
        ).fetchall()
    result: dict[int, set[str]] = {}
    for r in rows:
        result.setdefault(r["routine_id"], set()).add(r["date"])
    return result


def get_checks_for_date(day: str) -> set[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT routine_id FROM routine_checks WHERE date = ?", (day,)
        ).fetchall()
    return {r["routine_id"] for r in rows}

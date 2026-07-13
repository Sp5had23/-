import sqlite3
from pathlib import Path
from datetime import datetime, date

DB_PATH = Path("expenses.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                type     TEXT NOT NULL DEFAULT 'checkbox',
                unit     TEXT NOT NULL DEFAULT '',
                target   REAL NOT NULL DEFAULT 0,
                weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                active   INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS routine_checks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
                date       TEXT NOT NULL,
                value      REAL NOT NULL DEFAULT 1,
                UNIQUE(routine_id, date)
            )
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(routines)").fetchall()}
    if "type" not in cols:
        conn.execute("ALTER TABLE routines ADD COLUMN type TEXT NOT NULL DEFAULT 'checkbox'")
    if "unit" not in cols:
        conn.execute("ALTER TABLE routines ADD COLUMN unit TEXT NOT NULL DEFAULT ''")
    if "target" not in cols:
        conn.execute("ALTER TABLE routines ADD COLUMN target REAL NOT NULL DEFAULT 0")
    if "weekdays" not in cols:
        conn.execute("ALTER TABLE routines ADD COLUMN weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'")

    check_cols = {r[1] for r in conn.execute("PRAGMA table_info(routine_checks)").fetchall()}
    if "value" not in check_cols:
        conn.execute("ALTER TABLE routine_checks ADD COLUMN value REAL NOT NULL DEFAULT 1")


# ---------------------------------------------------------------------------
# Траты
# ---------------------------------------------------------------------------
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
def add_routine(name: str, rtype: str = "checkbox", unit: str = "",
                target: float = 0, weekdays: str = "0,1,2,3,4,5,6") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO routines (name, type, unit, target, weekdays) VALUES (?, ?, ?, ?, ?)",
            (name, rtype, unit, target, weekdays),
        )
        return cur.lastrowid


def delete_routine(routine_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM routine_checks WHERE routine_id = ?", (routine_id,))
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))


def get_routines() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM routines WHERE active = 1 ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def routine_is_scheduled(routine: dict, day: str) -> bool:
    """Проверяет, запланирована ли рутина на этот день недели."""
    try:
        d = date.fromisoformat(day)
        wd = str(d.weekday())
        return wd in routine.get("weekdays", "0,1,2,3,4,5,6").split(",")
    except ValueError:
        return True


def toggle_routine_check(routine_id: int, day: str) -> bool:
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
                "INSERT OR REPLACE INTO routine_checks (routine_id, date, value) VALUES (?, ?, 1)",
                (routine_id, day),
            )
            return True


def set_routine_value(routine_id: int, day: str, value: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO routine_checks (routine_id, date, value) VALUES (?, ?, ?)",
            (routine_id, day, value),
        )


def get_check_value(routine_id: int, day: str) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM routine_checks WHERE routine_id = ? AND date = ?",
            (routine_id, day),
        ).fetchone()
    return row["value"] if row else None


def get_checks_for_period(start_date: str, end_date: str) -> dict[int, dict[str, float]]:
    """Возвращает {routine_id: {date: value, ...}} за период."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT routine_id, date, value FROM routine_checks WHERE date >= ? AND date <= ?",
            (start_date, end_date),
        ).fetchall()
    result: dict[int, dict[str, float]] = {}
    for r in rows:
        result.setdefault(r["routine_id"], {})[r["date"]] = r["value"]
    return result


def get_checks_for_date(day: str) -> dict[int, float]:
    """Возвращает {routine_id: value} за день."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT routine_id, value FROM routine_checks WHERE date = ?", (day,)
        ).fetchall()
    return {r["routine_id"]: r["value"] for r in rows}

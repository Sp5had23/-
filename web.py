from datetime import date, datetime
import calendar

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from db import init_db, get_all, get_today, get_month, get_by_date, get_daily_totals, get_summary

app = FastAPI(title="Expense Tracker")
init_db()


def _rows_to_html(rows: list[dict]) -> str:
    if not rows:
        return '<tr><td colspan="4" class="empty-row">Нет записей</td></tr>'
    html = ""
    for r in rows:
        html += (
            f"<tr>"
            f"<td>{r['time']}</td>"
            f"<td class='desc'>{r['description']}</td>"
            f"<td class='amount'>{r['amount']:.2f}</td>"
            f"<td>{r['currency']}</td>"
            f"</tr>"
        )
    return html


def _totals_html(rows: list[dict]) -> str:
    totals = get_summary(rows)
    if not totals:
        return "<span class='total-badge empty'>0.00</span>"
    return " ".join(
        f"<span class='total-badge'>{cur}: {amt:.2f}</span>"
        for cur, amt in totals.items()
    )


def _build_calendar(year: int, month: int, daily: dict[str, float], selected: str | None) -> str:
    cal = calendar.Calendar(firstweekday=0)
    days = cal.monthdayscalendar(year, month)
    today_str = date.today().isoformat()

    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    html = f"""
    <div class="calendar-header">
      <a href="/calendar?y={prev_year}&m={prev_month}" class="cal-nav">&larr;</a>
      <span class="cal-title">{month_names[month]} {year}</span>
      <a href="/calendar?y={next_year}&m={next_month}" class="cal-nav">&rarr;</a>
    </div>
    <table class="calendar">
      <thead>
        <tr>
          <th>Пн</th><th>Вт</th><th>Ср</th><th>Чт</th><th>Пт</th><th>Сб</th><th>Вс</th>
        </tr>
      </thead>
      <tbody>
    """

    for week in days:
        html += "<tr>"
        for day_num in week:
            if day_num == 0:
                html += "<td class='cal-empty'></td>"
                continue

            day_str = f"{year:04d}-{month:02d}-{day_num:02d}"
            total = daily.get(day_str, 0)
            classes = ["cal-day"]
            if day_str == today_str:
                classes.append("cal-today")
            if day_str == selected:
                classes.append("cal-selected")
            if total > 0:
                classes.append("cal-has-data")

            amount_label = f"<span class='cal-amount'>{total:.0f}</span>" if total > 0 else ""

            html += (
                f"<td class='{' '.join(classes)}'>"
                f"<a href='/day/{day_str}?y={year}&m={month}'>"
                f"<span class='cal-num'>{day_num}</span>"
                f"{amount_label}"
                f"</a></td>"
            )
        html += "</tr>"

    html += "</tbody></table>"
    return html


def render_page(title: str, rows: list[dict], year: int, month: int, selected: str | None = None) -> str:
    daily = get_daily_totals(year, month)
    month_total = sum(daily.values())

    calendar_html = _build_calendar(year, month, daily, selected)
    table_html = _rows_to_html(rows)
    totals_html = _totals_html(rows)

    return PAGE_TEMPLATE.format(
        title=title,
        calendar_html=calendar_html,
        table_html=table_html,
        totals_html=totals_html,
        count=len(rows),
        month_total=f"{month_total:.2f}",
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(y: int | None = None, m: int | None = None):
    now = date.today()
    year = y or now.year
    month = m or now.month
    rows = get_month() if (year == now.year and month == now.month) else []
    daily = get_daily_totals(year, month)
    if year != now.year or month != now.month:
        prefix = f"{year:04d}-{month:02d}"
        from db import get_conn
        with get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM expenses WHERE date LIKE ? ORDER BY id DESC", (prefix + "%",)
            ).fetchall()
        rows = [dict(x) for x in r]
    return render_page(f"Траты за месяц", rows, year, month)


@app.get("/day/{day}", response_class=HTMLResponse)
async def day_view(day: str, y: int | None = None, m: int | None = None):
    rows = get_by_date(day)
    try:
        d = date.fromisoformat(day)
        year = y or d.year
        month = m or d.month
    except ValueError:
        year = y or date.today().year
        month = m or date.today().month

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    try:
        d = date.fromisoformat(day)
        weekday = day_names[d.weekday()]
        title = f"{weekday}, {d.strftime('%d.%m.%Y')}"
    except ValueError:
        title = day

    return render_page(title, rows, year, month, selected=day)


@app.get("/today", response_class=HTMLResponse)
async def today_view():
    now = date.today()
    rows = get_today()
    return render_page(f"Сегодня — {now.isoformat()}", rows, now.year, now.month, selected=now.isoformat())


@app.get("/api/all")
async def api_all():
    rows = get_all()
    return {"count": len(rows), "totals": get_summary(rows), "items": rows}


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Expense Tracker</title>
<style>
  :root {{
    --bg: #0f0f0f;
    --card: #1a1a2e;
    --border: #2a2a3e;
    --text: #e0e0e0;
    --muted: #888;
    --accent: #6c63ff;
    --green: #4caf50;
    --red: #ff5252;
    --hover: rgba(108, 99, 255, 0.08);
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 16px;
  }}
  .container {{
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.4rem;
    font-weight: 600;
    margin-bottom: 16px;
  }}

  /* --- Календарь --- */
  .calendar-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }}
  .cal-title {{
    font-size: 1.2rem;
    font-weight: 600;
  }}
  .cal-nav {{
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text);
    text-decoration: none;
    font-size: 1.2rem;
    transition: border-color 0.2s;
  }}
  .cal-nav:hover {{
    border-color: var(--accent);
  }}
  .calendar {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 4px;
    margin-bottom: 24px;
  }}
  .calendar th {{
    padding: 8px 0;
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    text-align: center;
  }}
  .calendar td {{
    border: none;
    padding: 0;
  }}
  .cal-empty {{
    background: transparent;
  }}
  .cal-day {{
    background: var(--card);
    border-radius: 10px;
    border: 1px solid var(--border);
    transition: border-color 0.2s, background 0.2s;
  }}
  .cal-day a {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 8px 4px;
    text-decoration: none;
    color: var(--text);
    min-height: 56px;
  }}
  .cal-day:hover {{
    border-color: var(--accent);
    background: var(--hover);
  }}
  .cal-num {{
    font-size: 0.95rem;
    font-weight: 500;
  }}
  .cal-amount {{
    font-size: 0.7rem;
    color: var(--red);
    font-weight: 600;
    margin-top: 2px;
  }}
  .cal-today {{
    border-color: var(--accent);
  }}
  .cal-today .cal-num {{
    color: var(--accent);
    font-weight: 700;
  }}
  .cal-selected {{
    background: var(--accent) !important;
    border-color: var(--accent) !important;
  }}
  .cal-selected a {{
    color: #fff !important;
  }}
  .cal-selected .cal-amount {{
    color: rgba(255,255,255,0.8) !important;
  }}
  .cal-has-data {{
    background: rgba(255, 82, 82, 0.06);
  }}

  /* --- Статистика --- */
  .stats {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .total-badge {{
    background: var(--card);
    border: 1px solid var(--green);
    color: var(--green);
    padding: 6px 14px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 1.05rem;
  }}
  .total-badge.empty {{
    border-color: var(--border);
    color: var(--muted);
  }}
  .count {{
    color: var(--muted);
    font-size: 0.85rem;
  }}

  /* --- Таблица расходов --- */
  .expenses {{
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}
  .expenses th {{
    text-align: left;
    padding: 12px 16px;
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
    background: rgba(108, 99, 255, 0.05);
  }}
  .expenses td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 0.95rem;
  }}
  .expenses tr:last-child td {{
    border-bottom: none;
  }}
  .expenses tr:hover td {{
    background: var(--hover);
  }}
  .amount {{
    font-weight: 600;
    color: var(--red);
    font-variant-numeric: tabular-nums;
  }}
  .desc {{
    max-width: 300px;
  }}
  .empty-row {{
    text-align: center;
    color: var(--muted);
    padding: 32px 16px !important;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 10px; }}
    .calendar {{ border-spacing: 3px; }}
    .cal-day a {{ min-height: 46px; padding: 6px 2px; }}
    .cal-num {{ font-size: 0.85rem; }}
    .expenses td, .expenses th {{ padding: 8px 10px; font-size: 0.85rem; }}
  }}
</style>
</head>
<body>
<div class="container">
  {calendar_html}

  <h1>{title}</h1>
  <div class="stats">
    {totals_html}
    <span class="count">{count} записей</span>
  </div>
  <table class="expenses">
    <thead>
      <tr>
        <th>Время</th>
        <th>Описание</th>
        <th>Сумма</th>
        <th>Валюта</th>
      </tr>
    </thead>
    <tbody>
      {table_html}
    </tbody>
  </table>
</div>
</body>
</html>"""

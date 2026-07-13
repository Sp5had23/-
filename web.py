from datetime import date, datetime, timedelta
import calendar as cal_module

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from db import (
    init_db, get_all, get_today, get_month, get_by_date,
    get_daily_totals, get_summary,
    get_routines, add_routine, delete_routine,
    toggle_routine_check, get_checks_for_date, get_checks_for_period,
)

app = FastAPI(title="Expense Tracker")
init_db()

MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


# =========================================================================
# Общий шаблон
# =========================================================================
def _base(title: str, content: str, active: str = "expenses") -> str:
    exp_cls = "active" if active == "expenses" else ""
    rut_cls = "active" if active == "routines" else ""
    return BASE_TEMPLATE.format(
        title=title,
        content=content,
        exp_cls=exp_cls,
        rut_cls=rut_cls,
    )


# =========================================================================
# Траты — хелперы
# =========================================================================
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


def _totals_badges(rows: list[dict]) -> str:
    totals = get_summary(rows)
    if not totals:
        return "<span class='badge badge-muted'>0.00</span>"
    return " ".join(
        f"<span class='badge badge-green'>{c}: {a:.2f}</span>"
        for c, a in totals.items()
    )


def _build_expense_calendar(year: int, month: int, daily: dict[str, float], selected: str | None) -> str:
    c = cal_module.Calendar(firstweekday=0)
    weeks = c.monthdayscalendar(year, month)
    today_str = date.today().isoformat()

    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    html = f"""
    <div class="cal-header">
      <a href="/expenses?y={prev_y}&m={prev_m}" class="cal-arrow">&larr;</a>
      <span class="cal-title">{MONTH_NAMES[month]} {year}</span>
      <a href="/expenses?y={next_y}&m={next_m}" class="cal-arrow">&rarr;</a>
    </div>
    <table class="cal"><thead><tr>
      <th>Пн</th><th>Вт</th><th>Ср</th><th>Чт</th><th>Пт</th><th>Сб</th><th>Вс</th>
    </tr></thead><tbody>
    """
    for week in weeks:
        html += "<tr>"
        for d in week:
            if d == 0:
                html += "<td class='cal-empty'></td>"
                continue
            ds = f"{year:04d}-{month:02d}-{d:02d}"
            total = daily.get(ds, 0)
            cls = ["cal-day"]
            if ds == today_str:
                cls.append("cal-today")
            if ds == selected:
                cls.append("cal-sel")
            if total > 0:
                cls.append("cal-has")
            amt = f"<span class='cal-amt'>{total:.0f}</span>" if total > 0 else ""
            html += (
                f"<td class='{' '.join(cls)}'>"
                f"<a href='/expenses/day/{ds}?y={year}&m={month}'>"
                f"<span class='cal-num'>{d}</span>{amt}</a></td>"
            )
        html += "</tr>"
    html += "</tbody></table>"
    return html


def render_expenses(title: str, rows: list[dict], year: int, month: int, selected: str | None = None) -> str:
    daily = get_daily_totals(year, month)
    calendar_html = _build_expense_calendar(year, month, daily, selected)

    content = f"""
    {calendar_html}
    <h2>{title}</h2>
    <div class="stats">
      {_totals_badges(rows)}
      <span class="count">{len(rows)} записей</span>
    </div>
    <table class="data-table">
      <thead><tr><th>Время</th><th>Описание</th><th>Сумма</th><th>Валюта</th></tr></thead>
      <tbody>{_rows_to_html(rows)}</tbody>
    </table>
    """
    return _base(title, content, "expenses")


# =========================================================================
# Траты — роуты
# =========================================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/expenses")


@app.get("/expenses", response_class=HTMLResponse)
@app.get("/calendar", response_class=HTMLResponse)
async def expenses_view(y: int | None = None, m: int | None = None):
    now = date.today()
    year, month = y or now.year, m or now.month
    prefix = f"{year:04d}-{month:02d}"
    from db import get_conn
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM expenses WHERE date LIKE ? ORDER BY id DESC", (prefix + "%",)
        ).fetchall()
    rows = [dict(x) for x in r]
    return render_expenses("Траты за месяц", rows, year, month)


@app.get("/expenses/day/{day}", response_class=HTMLResponse)
async def expenses_day(day: str, y: int | None = None, m: int | None = None):
    rows = get_by_date(day)
    try:
        d = date.fromisoformat(day)
        year, month = y or d.year, m or d.month
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        title = f"{day_names[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
    except ValueError:
        year, month = y or date.today().year, m or date.today().month
        title = day
    return render_expenses(title, rows, year, month, selected=day)


@app.get("/today", response_class=HTMLResponse)
async def expenses_today():
    now = date.today()
    rows = get_today()
    return render_expenses(f"Сегодня — {now.isoformat()}", rows, now.year, now.month, selected=now.isoformat())


@app.get("/api/all")
async def api_all():
    rows = get_all()
    return {"count": len(rows), "totals": get_summary(rows), "items": rows}


# =========================================================================
# Рутины — хелперы
# =========================================================================
def _build_routine_calendar(year: int, month: int, routines: list[dict], checks: dict[int, set[str]], selected: str | None) -> str:
    c = cal_module.Calendar(firstweekday=0)
    weeks = c.monthdayscalendar(year, month)
    today_str = date.today().isoformat()
    total_routines = len(routines) or 1

    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    # Подсчёт чеков по дням
    day_counts: dict[str, int] = {}
    for rid, dates in checks.items():
        for d in dates:
            day_counts[d] = day_counts.get(d, 0) + 1

    html = f"""
    <div class="cal-header">
      <a href="/routines?y={prev_y}&m={prev_m}" class="cal-arrow">&larr;</a>
      <span class="cal-title">{MONTH_NAMES[month]} {year}</span>
      <a href="/routines?y={next_y}&m={next_m}" class="cal-arrow">&rarr;</a>
    </div>
    <table class="cal"><thead><tr>
      <th>Пн</th><th>Вт</th><th>Ср</th><th>Чт</th><th>Пт</th><th>Сб</th><th>Вс</th>
    </tr></thead><tbody>
    """
    for week in weeks:
        html += "<tr>"
        for d in week:
            if d == 0:
                html += "<td class='cal-empty'></td>"
                continue
            ds = f"{year:04d}-{month:02d}-{d:02d}"
            done = day_counts.get(ds, 0)
            pct = int(done / total_routines * 100) if total_routines else 0
            cls = ["cal-day"]
            if ds == today_str:
                cls.append("cal-today")
            if ds == selected:
                cls.append("cal-sel")
            if pct == 100:
                cls.append("cal-done")
            elif pct > 0:
                cls.append("cal-partial")

            label = f"<span class='cal-pct'>{done}/{len(routines)}</span>" if done > 0 else ""
            html += (
                f"<td class='{' '.join(cls)}'>"
                f"<a href='/routines/day/{ds}?y={year}&m={month}'>"
                f"<span class='cal-num'>{d}</span>{label}</a></td>"
            )
        html += "</tr>"
    html += "</tbody></table>"
    return html


def render_routines_page(year: int, month: int, day: str | None = None) -> str:
    routines = get_routines()
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-31"
    checks = get_checks_for_period(start, end)

    calendar_html = _build_routine_calendar(year, month, routines, checks, day)

    # Чеклист на выбранный день
    show_day = day or date.today().isoformat()
    day_checks = get_checks_for_date(show_day)

    try:
        d = date.fromisoformat(show_day)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_title = f"{day_names[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
    except ValueError:
        day_title = show_day

    checklist_html = ""
    if not routines:
        checklist_html = "<p class='muted'>Нет рутин. Добавь первую ниже.</p>"
    else:
        for r in routines:
            checked = r["id"] in day_checks
            icon = "✅" if checked else "⬜"
            strike = " style='text-decoration:line-through;color:var(--muted)'" if checked else ""
            checklist_html += (
                f"<div class='routine-item'>"
                f"<a href='/routines/toggle/{r['id']}/{show_day}?y={year}&m={month}' class='routine-check'>{icon}</a>"
                f"<span class='routine-name'{strike}>{r['name']}</span>"
                f"<a href='/routines/delete/{r['id']}?y={year}&m={month}' class='routine-del' "
                f"onclick=\"return confirm('Удалить рутину «{r['name']}»?')\">✕</a>"
                f"</div>"
            )

    done_count = sum(1 for r in routines if r["id"] in day_checks)

    content = f"""
    {calendar_html}
    <h2>{day_title}</h2>
    <div class="stats">
      <span class="badge {'badge-green' if done_count == len(routines) and routines else 'badge-muted'}">{done_count}/{len(routines)} выполнено</span>
    </div>
    <div class="checklist">
      {checklist_html}
    </div>
    <form action="/routines/add?y={year}&m={month}" method="post" class="add-form">
      <input type="text" name="name" placeholder="Новая рутина…" required class="add-input">
      <button type="submit" class="add-btn">+</button>
    </form>
    """
    return _base(f"Рутины — {day_title}", content, "routines")


# =========================================================================
# Рутины — роуты
# =========================================================================
@app.get("/routines", response_class=HTMLResponse)
async def routines_view(y: int | None = None, m: int | None = None):
    now = date.today()
    return render_routines_page(y or now.year, m or now.month)


@app.get("/routines/day/{day}", response_class=HTMLResponse)
async def routines_day(day: str, y: int | None = None, m: int | None = None):
    try:
        d = date.fromisoformat(day)
        year, month = y or d.year, m or d.month
    except ValueError:
        year, month = y or date.today().year, m or date.today().month
    return render_routines_page(year, month, day)


@app.get("/routines/toggle/{routine_id}/{day}")
async def routines_toggle(routine_id: int, day: str, y: int | None = None, m: int | None = None):
    toggle_routine_check(routine_id, day)
    year = y or date.today().year
    month = m or date.today().month
    return RedirectResponse(f"/routines/day/{day}?y={year}&m={month}", status_code=303)


@app.post("/routines/add")
async def routines_add(name: str = Form(...), y: int | None = None, m: int | None = None):
    if name.strip():
        add_routine(name.strip())
    year = y or date.today().year
    month = m or date.today().month
    return RedirectResponse(f"/routines?y={year}&m={month}", status_code=303)


@app.get("/routines/delete/{routine_id}")
async def routines_del(routine_id: int, y: int | None = None, m: int | None = None):
    delete_routine(routine_id)
    year = y or date.today().year
    month = m or date.today().month
    return RedirectResponse(f"/routines?y={year}&m={month}", status_code=303)


# =========================================================================
# HTML-шаблон
# =========================================================================
BASE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
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
    --hover: rgba(108,99,255,0.08);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0;
  }}
  .wrap {{ max-width:900px; margin:0 auto; padding:16px; }}

  /* --- Навигация --- */
  .nav {{
    display: flex;
    border-bottom: 2px solid var(--border);
    margin-bottom: 20px;
    gap: 0;
  }}
  .nav a {{
    flex: 1;
    text-align: center;
    padding: 14px 0;
    text-decoration: none;
    color: var(--muted);
    font-weight: 600;
    font-size: 1rem;
    transition: color 0.2s;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
  }}
  .nav a:hover {{ color: var(--text); }}
  .nav a.active {{
    color: var(--accent);
    border-bottom-color: var(--accent);
  }}

  /* --- Календарь (общий) --- */
  .cal-header {{
    display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;
  }}
  .cal-title {{ font-size:1.15rem; font-weight:600; }}
  .cal-arrow {{
    width:38px; height:38px; display:flex; align-items:center; justify-content:center;
    background:var(--card); border:1px solid var(--border); border-radius:10px;
    color:var(--text); text-decoration:none; font-size:1.1rem;
    transition:border-color 0.2s;
  }}
  .cal-arrow:hover {{ border-color:var(--accent); }}
  .cal {{ width:100%; border-collapse:separate; border-spacing:4px; margin-bottom:20px; }}
  .cal th {{
    padding:6px 0; font-size:0.7rem; color:var(--muted);
    text-transform:uppercase; letter-spacing:0.5px; font-weight:500; text-align:center;
  }}
  .cal td {{ border:none; padding:0; }}
  .cal-empty {{ background:transparent; }}
  .cal-day {{
    background:var(--card); border-radius:10px; border:1px solid var(--border);
    transition:border-color 0.2s, background 0.2s;
  }}
  .cal-day a {{
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    padding:7px 3px; text-decoration:none; color:var(--text); min-height:52px;
  }}
  .cal-day:hover {{ border-color:var(--accent); background:var(--hover); }}
  .cal-num {{ font-size:0.9rem; font-weight:500; }}
  .cal-amt {{ font-size:0.65rem; color:var(--red); font-weight:600; margin-top:1px; }}
  .cal-pct {{ font-size:0.65rem; color:var(--green); font-weight:600; margin-top:1px; }}
  .cal-today {{ border-color:var(--accent); }}
  .cal-today .cal-num {{ color:var(--accent); font-weight:700; }}
  .cal-sel {{ background:var(--accent)!important; border-color:var(--accent)!important; }}
  .cal-sel a {{ color:#fff!important; }}
  .cal-sel .cal-amt, .cal-sel .cal-pct {{ color:rgba(255,255,255,0.8)!important; }}
  .cal-has {{ background:rgba(255,82,82,0.06); }}
  .cal-done {{ background:rgba(76,175,80,0.1); }}
  .cal-partial {{ background:rgba(255,193,7,0.08); }}

  /* --- Статы --- */
  h2 {{ font-size:1.3rem; font-weight:600; margin-bottom:12px; }}
  .stats {{ display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }}
  .badge {{
    padding:5px 12px; border-radius:8px; font-weight:600; font-size:0.95rem;
    background:var(--card); border:1px solid var(--border);
  }}
  .badge-green {{ border-color:var(--green); color:var(--green); }}
  .badge-muted {{ color:var(--muted); }}
  .count {{ color:var(--muted); font-size:0.85rem; }}

  /* --- Таблица расходов --- */
  .data-table {{
    width:100%; border-collapse:collapse; background:var(--card);
    border-radius:12px; overflow:hidden; border:1px solid var(--border);
  }}
  .data-table th {{
    text-align:left; padding:11px 14px; font-weight:600; font-size:0.78rem;
    color:var(--muted); text-transform:uppercase; letter-spacing:0.5px;
    border-bottom:1px solid var(--border); background:rgba(108,99,255,0.05);
  }}
  .data-table td {{
    padding:9px 14px; border-bottom:1px solid var(--border); font-size:0.93rem;
  }}
  .data-table tr:last-child td {{ border-bottom:none; }}
  .data-table tr:hover td {{ background:var(--hover); }}
  .amount {{ font-weight:600; color:var(--red); font-variant-numeric:tabular-nums; }}
  .desc {{ max-width:280px; }}
  .empty-row {{ text-align:center; color:var(--muted); padding:30px 14px!important; }}

  /* --- Рутины чеклист --- */
  .checklist {{ margin-bottom:16px; }}
  .routine-item {{
    display:flex; align-items:center; gap:12px;
    padding:12px 16px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; margin-bottom:6px; transition:border-color 0.2s;
  }}
  .routine-item:hover {{ border-color:var(--accent); }}
  .routine-check {{
    text-decoration:none; font-size:1.3rem; line-height:1;
    transition:transform 0.15s;
  }}
  .routine-check:hover {{ transform:scale(1.2); }}
  .routine-name {{ flex:1; font-size:0.95rem; }}
  .routine-del {{
    color:var(--muted); text-decoration:none; font-size:0.9rem; padding:4px;
    opacity:0.4; transition:opacity 0.2s;
  }}
  .routine-del:hover {{ opacity:1; color:var(--red); }}
  .muted {{ color:var(--muted); padding:20px 0; }}

  /* --- Форма добавления --- */
  .add-form {{
    display:flex; gap:8px; margin-top:12px;
  }}
  .add-input {{
    flex:1; padding:10px 14px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; color:var(--text); font-size:0.95rem; outline:none;
    transition:border-color 0.2s;
  }}
  .add-input:focus {{ border-color:var(--accent); }}
  .add-input::placeholder {{ color:var(--muted); }}
  .add-btn {{
    width:44px; background:var(--accent); border:none; border-radius:10px;
    color:#fff; font-size:1.4rem; cursor:pointer; transition:opacity 0.2s;
  }}
  .add-btn:hover {{ opacity:0.85; }}

  @media (max-width:600px) {{
    .wrap {{ padding:10px; }}
    .cal {{ border-spacing:3px; }}
    .cal-day a {{ min-height:44px; padding:5px 2px; }}
    .cal-num {{ font-size:0.8rem; }}
    .data-table td, .data-table th {{ padding:7px 9px; font-size:0.83rem; }}
    .routine-item {{ padding:10px 12px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <nav class="nav">
    <a href="/expenses" class="{exp_cls}">💰 Траты</a>
    <a href="/routines" class="{rut_cls}">📋 Рутины</a>
  </nav>
  {content}
</div>
</body>
</html>"""

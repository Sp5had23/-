from datetime import date, datetime, timedelta
import calendar as cal_module

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from db import (
    init_db, get_all, get_today, get_month, get_by_date,
    get_daily_totals, get_summary,
    get_routines, add_routine, delete_routine, routine_is_scheduled,
    toggle_routine_check, set_routine_value, get_check_value,
    get_checks_for_date, get_checks_for_period,
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


@app.get("/download")
async def download_db():
    from db import DB_PATH
    if DB_PATH.exists():
        return FileResponse(
            DB_PATH, filename="expenses.db", media_type="application/octet-stream"
        )
    return HTMLResponse("База пока пустая", status_code=404)


# =========================================================================
# Рутины — хелперы
# =========================================================================
DAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _build_routine_calendar(year: int, month: int, routines: list[dict],
                            checks: dict[int, dict[str, float]], selected: str | None) -> str:
    c = cal_module.Calendar(firstweekday=0)
    weeks = c.monthdayscalendar(year, month)
    today_str = date.today().isoformat()

    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    # Подсчёт: сколько из запланированных выполнено в каждый день
    day_done: dict[str, int] = {}
    day_scheduled: dict[str, int] = {}
    for ds_candidate in _month_dates(year, month):
        scheduled = sum(1 for r in routines if routine_is_scheduled(r, ds_candidate))
        done = sum(1 for r in routines if r["id"] in checks and ds_candidate in checks[r["id"]])
        if scheduled > 0:
            day_scheduled[ds_candidate] = scheduled
            day_done[ds_candidate] = done

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
            scheduled = day_scheduled.get(ds, 0)
            done = day_done.get(ds, 0)
            cls = ["cal-day"]
            if ds == today_str:
                cls.append("cal-today")
            if ds == selected:
                cls.append("cal-sel")
            if scheduled > 0 and done == scheduled:
                cls.append("cal-done")
            elif done > 0:
                cls.append("cal-partial")

            label = f"<span class='cal-pct'>{done}/{scheduled}</span>" if done > 0 else ""
            html += (
                f"<td class='{' '.join(cls)}'>"
                f"<a href='/routines/day/{ds}?y={year}&m={month}'>"
                f"<span class='cal-num'>{d}</span>{label}</a></td>"
            )
        html += "</tr>"
    html += "</tbody></table>"
    return html


def _month_dates(year: int, month: int) -> list[str]:
    import calendar
    _, last_day = calendar.monthrange(year, month)
    return [f"{year:04d}-{month:02d}-{d:02d}" for d in range(1, last_day + 1)]


def render_routines_page(year: int, month: int, day: str | None = None) -> str:
    routines = get_routines()
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-31"
    checks = get_checks_for_period(start, end)

    calendar_html = _build_routine_calendar(year, month, routines, checks, day)

    show_day = day or date.today().isoformat()
    day_checks = get_checks_for_date(show_day)

    try:
        d = date.fromisoformat(show_day)
        day_title = f"{DAY_LABELS[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
    except ValueError:
        day_title = show_day

    # Чеклист
    scheduled_routines = [r for r in routines if routine_is_scheduled(r, show_day)]
    other_routines = [r for r in routines if not routine_is_scheduled(r, show_day)]

    checklist_html = ""
    if not routines:
        checklist_html = "<p class='muted'>Нет рутин. Добавь первую ниже.</p>"
    elif not scheduled_routines:
        checklist_html = "<p class='muted'>На этот день ничего не запланировано.</p>"
    else:
        for r in scheduled_routines:
            checklist_html += _render_routine_item(r, show_day, day_checks, year, month)

    if other_routines:
        checklist_html += "<p class='muted' style='margin-top:16px;font-size:0.85rem'>Не на этот день:</p>"
        for r in other_routines:
            wd_labels = ", ".join(DAY_LABELS[int(x)] for x in r["weekdays"].split(",") if x.strip().isdigit())
            checklist_html += (
                f"<div class='routine-item' style='opacity:0.45'>"
                f"<span class='routine-name'>{r['name']}</span>"
                f"<span style='font-size:0.75rem;color:var(--muted)'>{wd_labels}</span>"
                f"<a href='/routines/delete/{r['id']}?y={year}&m={month}' class='routine-del' "
                f"onclick=\"return confirm('Удалить?')\">✕</a>"
                f"</div>"
            )

    done_count = sum(1 for r in scheduled_routines if r["id"] in day_checks)

    # Форма добавления
    weekday_checkboxes = ""
    for i, label in enumerate(DAY_LABELS):
        weekday_checkboxes += (
            f"<label class='wd-label'>"
            f"<input type='checkbox' name='weekdays' value='{i}' checked> {label}"
            f"</label>"
        )

    content = f"""
    {calendar_html}
    <h2>{day_title}</h2>
    <div class="stats">
      <span class="badge {'badge-green' if done_count == len(scheduled_routines) and scheduled_routines else 'badge-muted'}">{done_count}/{len(scheduled_routines)} выполнено</span>
    </div>
    <div class="checklist">
      {checklist_html}
    </div>

    <details class="add-section">
      <summary class="add-toggle">+ Добавить рутину</summary>
      <form action="/routines/add?y={year}&m={month}" method="post" class="add-form-full">
        <input type="text" name="name" placeholder="Название…" required class="add-input">

        <div class="form-row">
          <label class="form-label">Тип</label>
          <select name="type" class="form-select" onchange="document.getElementById('counter-opts').style.display=this.value==='counter'?'flex':'none'">
            <option value="checkbox">Галочка (да/нет)</option>
            <option value="counter">Счётчик (число)</option>
          </select>
        </div>

        <div class="form-row" id="counter-opts" style="display:none">
          <input type="text" name="unit" placeholder="Единица (л, шт, мин…)" class="add-input" style="flex:1">
          <input type="number" name="target" placeholder="Цель" step="0.1" min="0" class="add-input" style="width:90px">
        </div>

        <div class="form-row">
          <label class="form-label">Дни</label>
          <div class="wd-row">{weekday_checkboxes}</div>
        </div>

        <button type="submit" class="submit-btn">Добавить</button>
      </form>
    </details>
    """
    return _base(f"Рутины — {day_title}", content, "routines")


def _render_routine_item(r: dict, show_day: str, day_checks: dict[int, float],
                         year: int, month: int) -> str:
    rid = r["id"]
    rtype = r.get("type", "checkbox")
    unit = r.get("unit", "")
    target = r.get("target", 0)
    value = day_checks.get(rid)

    # Дни недели (компактно)
    weekdays = r.get("weekdays", "0,1,2,3,4,5,6")
    is_daily = weekdays == "0,1,2,3,4,5,6"
    schedule_label = ""
    if not is_daily:
        wd_labels = "".join(DAY_LABELS[int(x)][0] for x in weekdays.split(",") if x.strip().isdigit())
        schedule_label = f"<span class='routine-schedule'>{wd_labels}</span>"

    if rtype == "counter":
        current = value if value is not None else 0
        target_str = f" / {target:.1f}" if target > 0 else ""
        filled = value is not None and target > 0 and current >= target
        bar_pct = min(int(current / target * 100), 100) if target > 0 else 0
        bar_html = ""
        if target > 0:
            bar_html = f"<div class='progress-bar'><div class='progress-fill' style='width:{bar_pct}%'></div></div>"

        return (
            f"<div class='routine-item'>"
            f"<div class='routine-counter-row'>"
            f"<span class='routine-name{' done' if filled else ''}'>{r['name']}</span>"
            f"{schedule_label}"
            f"<form action='/routines/set/{rid}/{show_day}?y={year}&m={month}' method='post' class='counter-form'>"
            f"<button type='submit' name='delta' value='-0.5' class='counter-btn'>−</button>"
            f"<span class='counter-val'>{current:.1f}{target_str} {unit}</span>"
            f"<button type='submit' name='delta' value='0.5' class='counter-btn'>+</button>"
            f"</form>"
            f"<a href='/routines/delete/{rid}?y={year}&m={month}' class='routine-del' "
            f"onclick=\"return confirm('Удалить?')\">✕</a>"
            f"</div>"
            f"{bar_html}"
            f"</div>"
        )
    else:
        checked = value is not None
        icon = "✅" if checked else "⬜"
        strike = " done" if checked else ""
        return (
            f"<div class='routine-item'>"
            f"<a href='/routines/toggle/{rid}/{show_day}?y={year}&m={month}' class='routine-check'>{icon}</a>"
            f"<span class='routine-name{strike}'>{r['name']}</span>"
            f"{schedule_label}"
            f"<a href='/routines/delete/{rid}?y={year}&m={month}' class='routine-del' "
            f"onclick=\"return confirm('Удалить?')\">✕</a>"
            f"</div>"
        )


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


@app.post("/routines/set/{routine_id}/{day}")
async def routines_set_value(routine_id: int, day: str,
                             delta: float = Form(0), y: int | None = None, m: int | None = None):
    current = get_check_value(routine_id, day) or 0
    new_val = max(0, current + delta)
    if new_val > 0:
        set_routine_value(routine_id, day, new_val)
    else:
        # Удаляем если 0
        from db import get_conn
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM routine_checks WHERE routine_id = ? AND date = ?",
                (routine_id, day),
            )
    year = y or date.today().year
    month = m or date.today().month
    return RedirectResponse(f"/routines/day/{day}?y={year}&m={month}", status_code=303)


@app.post("/routines/add")
async def routines_add(name: str = Form(...), type: str = Form("checkbox"),
                       unit: str = Form(""), target: float = Form(0),
                       weekdays: list[str] = Form([]),
                       y: int | None = None, m: int | None = None):
    if name.strip():
        wd = ",".join(weekdays) if weekdays else "0,1,2,3,4,5,6"
        add_routine(name.strip(), rtype=type, unit=unit.strip(), target=target, weekdays=wd)
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
  .nav a.dl {{
    flex: none;
    padding: 14px 16px;
    font-size: 1.1rem;
    border-bottom: none;
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

  .routine-name.done {{
    text-decoration: line-through;
    color: var(--muted);
  }}
  .routine-schedule {{
    font-size:0.7rem; color:var(--accent); background:rgba(108,99,255,0.1);
    padding:2px 6px; border-radius:4px; letter-spacing:0.5px;
  }}

  /* --- Счётчик --- */
  .routine-counter-row {{
    display:flex; align-items:center; gap:10px; width:100%;
  }}
  .counter-form {{
    display:flex; align-items:center; gap:4px; margin-left:auto;
  }}
  .counter-btn {{
    width:30px; height:30px; border-radius:8px; border:1px solid var(--border);
    background:var(--card); color:var(--text); font-size:1.1rem; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    transition:border-color 0.2s;
  }}
  .counter-btn:hover {{ border-color:var(--accent); }}
  .counter-val {{
    font-size:0.9rem; font-weight:600; min-width:60px; text-align:center;
    font-variant-numeric:tabular-nums;
  }}
  .progress-bar {{
    width:100%; height:4px; background:var(--border); border-radius:2px; margin-top:8px;
  }}
  .progress-fill {{
    height:100%; background:var(--green); border-radius:2px; transition:width 0.3s;
  }}

  /* --- Форма добавления --- */
  .add-section {{ margin-top:20px; }}
  .add-toggle {{
    cursor:pointer; color:var(--accent); font-weight:600; font-size:0.95rem;
    padding:10px 0; list-style:none;
  }}
  .add-toggle::-webkit-details-marker {{ display:none; }}
  .add-form-full {{
    display:flex; flex-direction:column; gap:10px; margin-top:12px;
    padding:16px; background:var(--card); border:1px solid var(--border); border-radius:12px;
  }}
  .form-row {{
    display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  }}
  .form-label {{
    font-size:0.85rem; color:var(--muted); min-width:40px;
  }}
  .form-select {{
    flex:1; padding:8px 12px; background:var(--bg); border:1px solid var(--border);
    border-radius:8px; color:var(--text); font-size:0.9rem; outline:none;
  }}
  .form-select:focus {{ border-color:var(--accent); }}
  .wd-row {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .wd-label {{
    font-size:0.8rem; color:var(--text); display:flex; align-items:center; gap:3px;
    padding:4px 8px; background:var(--bg); border:1px solid var(--border);
    border-radius:6px; cursor:pointer; transition:border-color 0.2s;
  }}
  .wd-label:has(input:checked) {{ border-color:var(--accent); color:var(--accent); }}
  .wd-label input {{ display:none; }}
  .add-input {{
    flex:1; padding:10px 14px; background:var(--bg); border:1px solid var(--border);
    border-radius:10px; color:var(--text); font-size:0.95rem; outline:none;
    transition:border-color 0.2s;
  }}
  .add-input:focus {{ border-color:var(--accent); }}
  .add-input::placeholder {{ color:var(--muted); }}
  .submit-btn {{
    padding:10px; background:var(--accent); border:none; border-radius:10px;
    color:#fff; font-size:0.95rem; font-weight:600; cursor:pointer; transition:opacity 0.2s;
  }}
  .submit-btn:hover {{ opacity:0.85; }}

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
    <a href="/download" class="dl">💾</a>
  </nav>
  {content}
</div>
</body>
</html>"""

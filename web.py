from datetime import date, datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from db import init_db, get_all, get_today, get_month, get_summary

app = FastAPI(title="Expense Tracker")
init_db()


def render_table(rows: list[dict], title: str) -> str:
    totals = get_summary(rows)
    total_html = ""
    if totals:
        parts = [f"<span class='total-badge'>{cur}: {amt:.2f}</span>" for cur, amt in totals.items()]
        total_html = " ".join(parts)
    else:
        total_html = "<span class='total-badge empty'>Пока пусто</span>"

    rows_html = ""
    for r in rows:
        rows_html += f"""
        <tr>
            <td>{r['date']}</td>
            <td>{r['time']}</td>
            <td class="desc">{r['description']}</td>
            <td class="amount">{r['amount']:.2f}</td>
            <td>{r['currency']}</td>
        </tr>"""

    if not rows:
        rows_html = '<tr><td colspan="5" class="empty-row">Нет записей</td></tr>'

    return PAGE_TEMPLATE.format(
        title=title,
        total_html=total_html,
        count=len(rows),
        rows_html=rows_html,
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    rows = get_all()
    return render_table(rows, "Все траты")


@app.get("/today", response_class=HTMLResponse)
async def today():
    rows = get_today()
    return render_table(rows, f"Сегодня — {date.today().isoformat()}")


@app.get("/month", response_class=HTMLResponse)
async def month():
    rows = get_month()
    return render_table(rows, f"Месяц — {datetime.now().strftime('%Y-%m')}")


@app.get("/api/all")
async def api_all():
    rows = get_all()
    return {"count": len(rows), "totals": get_summary(rows), "items": rows}


PAGE_TEMPLATE = """<!DOCTYPE html>
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
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 20px;
  }}
  .container {{
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 16px;
  }}
  .nav {{
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }}
  .nav a {{
    padding: 8px 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    text-decoration: none;
    font-size: 0.9rem;
    transition: border-color 0.2s;
  }}
  .nav a:hover {{
    border-color: var(--accent);
  }}
  .stats {{
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
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
    font-size: 1.1rem;
  }}
  .total-badge.empty {{
    border-color: var(--border);
    color: var(--muted);
  }}
  .count {{
    color: var(--muted);
    font-size: 0.9rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}
  th {{
    text-align: left;
    padding: 12px 16px;
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
    background: rgba(108, 99, 255, 0.05);
  }}
  td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 0.95rem;
  }}
  tr:last-child td {{
    border-bottom: none;
  }}
  tr:hover td {{
    background: rgba(108, 99, 255, 0.04);
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
    padding: 40px 16px;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 12px; }}
    td, th {{ padding: 8px 10px; font-size: 0.85rem; }}
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{title}</h1>
  <nav class="nav">
    <a href="/">Все</a>
    <a href="/today">Сегодня</a>
    <a href="/month">Месяц</a>
  </nav>
  <div class="stats">
    {total_html}
    <span class="count">{count} записей</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Дата</th>
        <th>Время</th>
        <th>Описание</th>
        <th>Сумма</th>
        <th>Валюта</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>
</body>
</html>"""

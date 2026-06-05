from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


AW_BASE = "http://localhost:5600/api/0"
ANDROID_AW_BASE = "http://127.0.0.1:5601/api/0"
HOST = "127.0.0.1"
PORT = 8765
JST = timezone(timedelta(hours=9))
CACHE_TTL_SECONDS = 45
SUMMARY_CACHE: dict[int, tuple[float, dict]] = {}


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(url: str, timeout: int = 20):
    req = Request(url, headers={"User-Agent": "ActivityWatch Local Dashboard"})
    with urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def aw_get(path: str, params: dict | None = None, base: str = AW_BASE, timeout: int = 20):
    url = f"{base}{path}"
    if params:
        url += "?" + urlencode(params)
    return get_json(url, timeout=timeout)


def classify_bucket(bucket_id: str) -> str:
    lower = bucket_id.lower()
    if "android" in lower:
        return "android"
    if "window" in lower:
        return "window"
    if "afk" in lower:
        return "afk"
    if "web" in lower or "browser" in lower:
        return "web"
    return "other"


def pick_buckets(buckets: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"window": [], "afk": [], "android": [], "web": [], "other": []}
    for bucket_id in buckets:
        result[classify_bucket(bucket_id)].append(bucket_id)
    return result


def fetch_events(bucket_id: str, start: datetime, end: datetime, base: str = AW_BASE) -> list[dict]:
    try:
        events = aw_get(
            f"/buckets/{bucket_id}/events",
            {"start": iso_z(start), "end": iso_z(end)},
            base=base,
        )
        return events if isinstance(events, list) else []
    except Exception:
        return []


def get_android_bridge_buckets() -> list[str]:
    try:
        buckets = aw_get("/buckets", base=ANDROID_AW_BASE, timeout=2)
    except Exception:
        return []
    if not isinstance(buckets, dict):
        return []
    return list(buckets.keys())


def event_label(event: dict, fallback: str = "unknown") -> str:
    data = event.get("data") or {}
    for key in ("app", "package", "title", "name", "status"):
        value = data.get(key)
        if value:
            return str(value)
    return fallback


def event_title(event: dict) -> str:
    data = event.get("data") or {}
    return str(data.get("title") or data.get("app") or data.get("package") or "")


def duration(event: dict) -> float:
    try:
        return max(0.0, float(event.get("duration") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def round_minutes(seconds: float) -> float:
    return round(seconds / 60, 1)


def round_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def median(values: list[float]) -> float:
    clean = [v for v in values if v > 0]
    return statistics.median(clean) if clean else 0.0


def day_bounds(days: int) -> list[tuple[datetime, datetime]]:
    now = datetime.now(JST)
    today = datetime(now.year, now.month, now.day, tzinfo=JST)
    start = today - timedelta(days=days - 1)
    return [(start + timedelta(days=i), start + timedelta(days=i + 1)) for i in range(days)]


def current_month_bounds() -> list[tuple[datetime, datetime]]:
    now = datetime.now(JST)
    start = datetime(now.year, now.month, 1, tzinfo=JST)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=JST)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=JST)
    days = (next_month - start).days
    return [(start + timedelta(days=i), start + timedelta(days=i + 1)) for i in range(days)]


def summarize_usage(groups: dict[str, list[str]], start: datetime, end: datetime) -> dict:
    capped_end = min(end, datetime.now(JST))
    window_seconds = 0.0
    afk_active_seconds = 0.0
    android_seconds = 0.0

    if capped_end <= start:
        return {"window": 0.0, "active": 0.0, "android": 0.0, "total": 0.0}

    for bucket_id in groups["window"] + groups["web"]:
        for event in fetch_events(bucket_id, start, capped_end):
            window_seconds += duration(event)

    for bucket_id in groups["afk"]:
        for event in fetch_events(bucket_id, start, capped_end):
            if (event.get("data") or {}).get("status") == "not-afk":
                afk_active_seconds += duration(event)

    for bucket_id in groups["android"]:
        for event in fetch_events(bucket_id, start, capped_end):
            android_seconds += duration(event)

    return {
        "window": window_seconds,
        "active": afk_active_seconds,
        "android": android_seconds,
        "total": max(window_seconds, afk_active_seconds) + android_seconds,
    }


def empty_usage() -> dict:
    return {"window": 0.0, "active": 0.0, "android": 0.0}


def build_calendar(usage_by_date: dict[str, dict]) -> dict:
    bounds = current_month_bounds()
    month_days = []
    for start, end in bounds:
        usage = usage_by_date.get(start.strftime("%Y-%m-%d"), empty_usage())
        total = max(usage["window"], usage["active"]) + usage["android"]
        month_days.append(
            {
                "date": start.strftime("%Y-%m-%d"),
                "day": start.day,
                "weekday": start.weekday(),
                "isFuture": start > datetime.now(JST),
                "hours": round_hours(total),
                "pcHours": round_hours(max(usage["window"], usage["active"])),
                "androidHours": round_hours(usage["android"]),
            }
        )
    active_days = [d for d in month_days if not d["isFuture"] and d["hours"] > 0]
    return {
        "month": bounds[0][0].strftime("%Y-%m"),
        "firstWeekday": bounds[0][0].weekday(),
        "activeDays": len(active_days),
        "daysSoFar": len([d for d in month_days if not d["isFuture"]]),
        "maxHours": round(max([d["hours"] for d in month_days] or [0]), 2),
        "days": month_days,
    }


def collect_summary(days: int) -> dict:
    cached = SUMMARY_CACHE.get(days)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        data = dict(cached[1])
        data["cached"] = True
        return data

    buckets = aw_get("/buckets")
    groups = pick_buckets(buckets)
    android_bridge_buckets = get_android_bridge_buckets()
    groups["android_bridge"] = android_bridge_buckets
    bounds = day_bounds(days)
    today_start, today_end = bounds[-1][0], datetime.now(JST)
    month_bounds = current_month_bounds()
    selected_start = bounds[0][0]
    selected_end = min(bounds[-1][1], today_end)
    fetch_start = min(selected_start, month_bounds[0][0])

    app_seconds: dict[str, float] = {}
    title_seconds: dict[str, float] = {}
    hourly_seconds = [0.0 for _ in range(24)]
    usage_by_date: dict[str, dict] = {}
    today_events = []

    def usage_for(dt: datetime) -> dict:
        key = dt.strftime("%Y-%m-%d")
        if key not in usage_by_date:
            usage_by_date[key] = empty_usage()
        return usage_by_date[key]

    for bucket_id in groups["window"] + groups["web"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            event_start = parse_aw_time(event.get("timestamp"))
            if not event_start:
                continue
            event_local = event_start.astimezone(JST)
            sec = duration(event)
            usage_for(event_local)["window"] += sec
            if selected_start <= event_local < selected_end:
                label = event_label(event, "window")
                title = event_title(event)
                app_seconds[label] = app_seconds.get(label, 0.0) + sec
                if title:
                    title_seconds[title] = title_seconds.get(title, 0.0) + sec
                hourly_seconds[event_local.hour] += sec
            if today_start <= event_local <= today_end:
                today_events.append(event)

    for bucket_id in groups["afk"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            if (event.get("data") or {}).get("status") != "not-afk":
                continue
            event_start = parse_aw_time(event.get("timestamp"))
            if not event_start:
                continue
            usage_for(event_start.astimezone(JST))["active"] += duration(event)

    for bucket_id in groups["android"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            event_start = parse_aw_time(event.get("timestamp"))
            if not event_start:
                continue
            event_local = event_start.astimezone(JST)
            sec = duration(event)
            usage_for(event_local)["android"] += sec
            if selected_start <= event_local < selected_end:
                label = event_label(event, "android")
                app_seconds[f"Android: {label}"] = app_seconds.get(f"Android: {label}", 0.0) + sec
                hourly_seconds[event_local.hour] += sec
            if today_start <= event_local <= today_end:
                today_events.append(event)

    for bucket_id in groups["android_bridge"]:
        for event in fetch_events(bucket_id, fetch_start, today_end, base=ANDROID_AW_BASE):
            event_start = parse_aw_time(event.get("timestamp"))
            if not event_start:
                continue
            event_local = event_start.astimezone(JST)
            sec = duration(event)
            usage_for(event_local)["android"] += sec
            if selected_start <= event_local < selected_end:
                label = event_label(event, "android")
                app_seconds[f"Android: {label}"] = app_seconds.get(f"Android: {label}", 0.0) + sec
                hourly_seconds[event_local.hour] += sec
            if today_start <= event_local <= today_end:
                today_events.append(event)

    daily = []
    total_window_seconds = 0.0
    total_afk_active_seconds = 0.0
    total_android_seconds = 0.0

    for start, end in bounds:
        usage = usage_by_date.get(start.strftime("%Y-%m-%d"), empty_usage())
        window_seconds = usage["window"]
        afk_active_seconds = usage["active"]
        android_seconds = usage["android"]
        total_window_seconds += window_seconds
        total_afk_active_seconds += afk_active_seconds
        total_android_seconds += android_seconds

        daily.append(
            {
                "date": start.strftime("%Y-%m-%d"),
                "pcWindowHours": round_hours(window_seconds),
                "pcActiveHours": round_hours(afk_active_seconds),
                "androidHours": round_hours(android_seconds),
                "totalHours": round_hours(max(window_seconds, afk_active_seconds) + android_seconds),
            }
        )

    daily_totals = [d["totalHours"] for d in daily]
    top_apps = sorted(app_seconds.items(), key=lambda item: item[1], reverse=True)[:12]
    top_titles = sorted(title_seconds.items(), key=lambda item: item[1], reverse=True)[:12]
    today_events = sorted(today_events, key=lambda e: e.get("timestamp") or "", reverse=True)[:24]

    result = {
        "ok": True,
        "cached": False,
        "generatedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "days": days,
        "buckets": groups,
        "hasAndroid": bool(groups["android"] or groups["android_bridge"]),
        "androidBridgeUrl": ANDROID_AW_BASE,
        "stats": {
            "todayHours": daily[-1]["totalHours"] if daily else 0,
            "periodTotalHours": round(sum(daily_totals), 2),
            "averageHours": round(sum(daily_totals) / len(daily_totals), 2) if daily_totals else 0,
            "medianHours": round(median(daily_totals), 2),
            "maxHours": round(max(daily_totals), 2) if daily_totals else 0,
            "pcWindowHours": round_hours(total_window_seconds),
            "pcActiveHours": round_hours(total_afk_active_seconds),
            "androidHours": round_hours(total_android_seconds),
        },
        "daily": daily,
        "calendar": build_calendar(usage_by_date),
        "hourly": [{"hour": h, "minutes": round_minutes(sec)} for h, sec in enumerate(hourly_seconds)],
        "topApps": [{"name": name, "minutes": round_minutes(sec)} for name, sec in top_apps],
        "topTitles": [{"name": name[:140], "minutes": round_minutes(sec)} for name, sec in top_titles],
        "recent": [
            {
                "time": local_time(e.get("timestamp")),
                "name": event_label(e),
                "title": event_title(e)[:160],
                "minutes": round_minutes(duration(e)),
            }
            for e in today_events
        ],
    }
    SUMMARY_CACHE[days] = (time.time(), result)
    return result


def parse_aw_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def local_time(value: str | None) -> str:
    dt = parse_aw_time(value)
    return dt.astimezone(JST).strftime("%H:%M") if dt else ""


INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PCライフログ統計</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #1c2430;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0f766e;
      --accent2: #7c3aed;
      --warn: #c2410c;
      --shadow: 0 8px 26px rgba(28, 36, 48, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      position: sticky;
      top: 0;
      z-index: 2;
      backdrop-filter: blur(10px);
    }
    h1 { margin: 0; font-size: 22px; font-weight: 700; }
    main { max-width: 1180px; margin: 0 auto; padding: 22px; }
    button, select {
      height: 36px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 0 12px;
      font: inherit;
      color: var(--ink);
    }
    button.primary { background: var(--accent); border-color: var(--accent); color: white; }
    .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .status { color: var(--muted); font-size: 13px; min-width: 190px; text-align: right; }
    .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 18px; }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .card { padding: 16px; min-height: 112px; }
    .label { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
    .value { font-size: 32px; font-weight: 750; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 6px; }
    .layout { display: grid; grid-template-columns: 1.15fr .85fr; gap: 16px; align-items: start; }
    .panel { padding: 16px; margin-bottom: 16px; }
    h2 { margin: 0 0 12px; font-size: 17px; }
    .panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .panel-head h2 { margin: 0; }
    .hint { color: var(--muted); font-size: 12px; }
    .calendar-meta { display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin-bottom: 12px; }
    .calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
    .weekday { color: var(--muted); font-size: 12px; text-align: center; padding-bottom: 2px; }
    .cal-day {
      min-height: 74px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 7px;
      background: #f8fafc;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 8px;
    }
    .cal-day.empty { border-color: transparent; background: transparent; box-shadow: none; }
    .cal-day.future { opacity: .38; }
    .cal-num { color: var(--muted); font-size: 12px; }
    .cal-hours { font-size: 16px; font-weight: 750; font-variant-numeric: tabular-nums; }
    .cal-split { display: flex; height: 4px; overflow: hidden; border-radius: 999px; background: rgba(255,255,255,.58); }
    .cal-pc { background: #0f766e; }
    .cal-android { background: #7c3aed; }
    .insights { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
    .insight { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 12px; box-shadow: var(--shadow); min-height: 82px; }
    .insight strong { display: block; font-size: 15px; margin-bottom: 6px; }
    .insight span { color: var(--muted); font-size: 13px; }
    .bars { display: flex; flex-direction: column; gap: 10px; }
    .bar-row { display: grid; grid-template-columns: minmax(120px, 1fr) 80px; gap: 10px; align-items: center; }
    .bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
    .track { height: 9px; background: #e8edf2; border-radius: 999px; overflow: hidden; margin-top: 4px; }
    .fill { height: 100%; background: var(--accent); border-radius: 999px; min-width: 2px; }
    .bar-value { font-variant-numeric: tabular-nums; color: var(--muted); text-align: right; font-size: 13px; }
    .daily { display: grid; grid-template-columns: repeat(auto-fit, minmax(48px, 1fr)); gap: 8px; align-items: end; height: 220px; padding-top: 8px; }
    .day { display: flex; flex-direction: column; gap: 6px; align-items: center; min-width: 0; }
    .day-bar { width: 100%; min-height: 2px; background: var(--accent2); border-radius: 4px 4px 0 0; }
    .day small { color: var(--muted); font-size: 11px; writing-mode: vertical-rl; transform: rotate(180deg); height: 60px; }
    .hours { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; }
    .hour { height: 48px; border-radius: 4px; background: #e8edf2; position: relative; }
    .hour span { position: absolute; bottom: -18px; left: 0; font-size: 10px; color: var(--muted); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 8px 6px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    td:last-child, th:last-child { text-align: right; }
    .notice { border-left: 4px solid var(--warn); padding: 10px 12px; background: #fff7ed; color: #7c2d12; border-radius: 6px; margin-bottom: 16px; }
    .empty { color: var(--muted); padding: 18px 0; }
    @media (max-width: 880px) {
      header { align-items: flex-start; flex-direction: column; }
      .status { text-align: left; }
      .grid { grid-template-columns: repeat(2, 1fr); }
      .layout { grid-template-columns: 1fr; }
      .insights { grid-template-columns: 1fr; }
    }
    @media (max-width: 520px) {
      main { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
      .value { font-size: 28px; }
      .hours { grid-template-columns: repeat(12, 1fr); row-gap: 20px; }
      .cal-day { min-height: 58px; padding: 5px; }
      .cal-hours { font-size: 13px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>PCライフログ統計</h1>
      <div class="sub">ActivityWatchから読み取り専用で集計</div>
    </div>
    <div class="controls">
      <select id="days">
        <option value="1">今日</option>
        <option value="7" selected>直近7日</option>
        <option value="14">直近14日</option>
        <option value="30">直近30日</option>
      </select>
      <button class="primary" id="reload">更新</button>
      <div class="status" id="status">読み込み中...</div>
    </div>
  </header>
  <main>
    <div id="notice"></div>
    <section class="grid">
      <div class="card"><div class="label">今日の合計</div><div class="value" id="today">--</div><div class="sub">PC + Android</div></div>
      <div class="card"><div class="label">期間合計</div><div class="value" id="period">--</div><div class="sub" id="periodSub">--</div></div>
      <div class="card"><div class="label">1日平均</div><div class="value" id="average">--</div><div class="sub">中央値 <span id="median">--</span></div></div>
      <div class="card"><div class="label">最大の日</div><div class="value" id="max">--</div><div class="sub">使いすぎ検知の基準にできる</div></div>
    </section>
    <section class="insights" id="insights"></section>
    <section class="layout">
      <div>
        <div class="panel">
          <div class="panel-head">
            <h2>月間カレンダー</h2>
            <div class="hint">色が濃いほど使用時間が長い</div>
          </div>
          <div class="calendar-meta" id="calendarMeta"></div>
          <div class="calendar-grid" id="calendar"></div>
        </div>
        <div class="panel">
          <h2>日別推移</h2>
          <div class="daily" id="daily"></div>
        </div>
        <div class="panel">
          <h2>時間帯ヒート</h2>
          <div class="hours" id="hourly"></div>
        </div>
        <div class="panel">
          <h2>最近の記録</h2>
          <table>
            <thead><tr><th>時刻</th><th>アプリ</th><th>タイトル</th><th>分</th></tr></thead>
            <tbody id="recent"></tbody>
          </table>
        </div>
      </div>
      <div>
        <div class="panel">
          <h2>アプリ別</h2>
          <div class="bars" id="apps"></div>
        </div>
        <div class="panel">
          <h2>ウィンドウ別</h2>
          <div class="bars" id="titles"></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const fmtHours = v => `${Number(v || 0).toFixed(2)}h`;
    const fmtMinutes = v => `${Number(v || 0).toFixed(1)}m`;
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

    async function load() {
      const days = document.getElementById('days').value;
      document.getElementById('status').textContent = '読み込み中...';
      try {
        const res = await fetch(`/api/summary?days=${days}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.message || '読み込み失敗');
        render(data);
        document.getElementById('status').textContent = `更新 ${data.generatedAt.slice(11, 19)}`;
      } catch (err) {
        document.getElementById('status').textContent = '接続エラー';
        document.getElementById('notice').innerHTML = `<div class="notice">ActivityWatchに接続できません。ActivityWatchを起動してから、この画面を更新してください。<br>${esc(err.message)}</div>`;
      }
    }

    function render(data) {
      document.getElementById('notice').innerHTML = data.hasAndroid ? '' : '<div class="notice">AndroidのバケットはまだPC側に見えていません。同期できると、この画面にAndroid使用時間も自動で合算されます。</div>';
      document.getElementById('today').textContent = fmtHours(data.stats.todayHours);
      document.getElementById('period').textContent = fmtHours(data.stats.periodTotalHours);
      document.getElementById('periodSub').textContent = `${data.days}日分`;
      document.getElementById('average').textContent = fmtHours(data.stats.averageHours);
      document.getElementById('median').textContent = fmtHours(data.stats.medianHours);
      document.getElementById('max').textContent = fmtHours(data.stats.maxHours);
      renderInsights(data);
      renderCalendar(data.calendar);

      const maxDaily = Math.max(...data.daily.map(d => d.totalHours), 0.1);
      document.getElementById('daily').innerHTML = data.daily.map(d => {
        const h = Math.max(2, (d.totalHours / maxDaily) * 150);
        return `<div class="day" title="${d.date} ${fmtHours(d.totalHours)}"><div>${fmtHours(d.totalHours)}</div><div class="day-bar" style="height:${h}px"></div><small>${d.date}</small></div>`;
      }).join('');

      const maxHour = Math.max(...data.hourly.map(h => h.minutes), 0.1);
      document.getElementById('hourly').innerHTML = data.hourly.map(h => {
        const alpha = Math.min(1, Math.max(.08, h.minutes / maxHour));
        return `<div class="hour" title="${h.hour}:00 ${fmtMinutes(h.minutes)}" style="background: rgba(15,118,110,${alpha})"><span>${h.hour}</span></div>`;
      }).join('');

      renderBars('apps', data.topApps);
      renderBars('titles', data.topTitles);
      document.getElementById('recent').innerHTML = data.recent.length ? data.recent.map(r =>
        `<tr><td>${esc(r.time)}</td><td>${esc(r.name)}</td><td>${esc(r.title)}</td><td>${fmtMinutes(r.minutes)}</td></tr>`
      ).join('') : '<tr><td colspan="4" class="empty">今日の記録がまだ少ないです</td></tr>';
    }

    function renderInsights(data) {
      const topApp = data.topApps[0]?.name || 'まだデータなし';
      const peak = data.hourly.reduce((best, row) => row.minutes > best.minutes ? row : best, { hour: 0, minutes: 0 });
      const activeRate = data.calendar.daysSoFar ? Math.round(data.calendar.activeDays / data.calendar.daysSoFar * 100) : 0;
      document.getElementById('insights').innerHTML = `
        <div class="insight"><strong>今月の記録日 ${data.calendar.activeDays}/${data.calendar.daysSoFar}</strong><span>記録がある日数。習慣の途切れ方が見える。</span></div>
        <div class="insight"><strong>ピーク時間 ${peak.hour}:00台</strong><span>${fmtMinutes(peak.minutes)}。集中/だらだらの山を探す入口。</span></div>
        <div class="insight"><strong>主役アプリ ${esc(topApp)}</strong><span>期間内でいちばん長く前面にいたアプリ。</span></div>
      `;
    }

    function renderCalendar(calendar) {
      const weekdays = ['月', '火', '水', '木', '金', '土', '日'];
      const max = Math.max(calendar.maxHours, 0.1);
      const blanks = Array.from({ length: calendar.firstWeekday }, () => '<div class="cal-day empty"></div>').join('');
      const cells = calendar.days.map(d => {
        const intensity = Math.min(1, Math.max(0, d.hours / max));
        const bg = d.hours > 0 ? `linear-gradient(135deg, rgba(15,118,110,${0.14 + intensity * 0.62}), rgba(124,58,237,${0.07 + intensity * 0.34}))` : '#f8fafc';
        const total = Math.max(d.pcHours + d.androidHours, 0.01);
        const pcWidth = Math.max(0, d.pcHours / total * 100);
        const androidWidth = Math.max(0, d.androidHours / total * 100);
        return `<div class="cal-day ${d.isFuture ? 'future' : ''}" style="background:${bg}" title="${d.date} PC ${fmtHours(d.pcHours)} / Android ${fmtHours(d.androidHours)}">
          <div class="cal-num">${d.day}</div>
          <div class="cal-hours">${fmtHours(d.hours)}</div>
          <div class="cal-split"><div class="cal-pc" style="width:${pcWidth}%"></div><div class="cal-android" style="width:${androidWidth}%"></div></div>
        </div>`;
      }).join('');
      document.getElementById('calendarMeta').innerHTML = `<span>${calendar.month}</span><span>最大 ${fmtHours(calendar.maxHours)}</span><span>緑: PC / 紫: Android</span>`;
      document.getElementById('calendar').innerHTML = weekdays.map(w => `<div class="weekday">${w}</div>`).join('') + blanks + cells;
    }

    function renderBars(id, rows) {
      const max = Math.max(...rows.map(r => r.minutes), 0.1);
      document.getElementById(id).innerHTML = rows.length ? rows.map(r => `
        <div class="bar-row" title="${esc(r.name)}">
          <div>
            <div class="bar-label">${esc(r.name)}</div>
            <div class="track"><div class="fill" style="width:${Math.max(2, r.minutes / max * 100)}%"></div></div>
          </div>
          <div class="bar-value">${fmtMinutes(r.minutes)}</div>
        </div>
      `).join('') : '<div class="empty">データなし</div>';
    }

    document.getElementById('reload').addEventListener('click', load);
    document.getElementById('days').addEventListener('change', load);
    load();
    setInterval(load, 60000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/summary":
            qs = parse_qs(parsed.query)
            try:
                days = int(qs.get("days", ["7"])[0])
            except ValueError:
                days = 7
            days = max(1, min(days, 30))
            try:
                self.send_json(collect_summary(days))
            except (HTTPError, URLError, TimeoutError) as exc:
                self.send_json({"ok": False, "message": str(exc)}, status=502)
            except Exception as exc:
                self.send_json({"ok": False, "message": str(exc)}, status=500)
            return
        self.send_json({"ok": False, "message": "not found"}, status=404)

    def log_message(self, fmt, *args):
        return

    def send_text(self, text: str, content_type: str, status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict, status: int = 200):
        self.send_text(json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8", status)


def open_browser_later(url: str):
    time.sleep(0.8)
    webbrowser.open(url)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"PCライフログ統計: {url}")
    if "--no-open" not in sys.argv:
        threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します")


if __name__ == "__main__":
    main()

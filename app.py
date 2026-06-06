from __future__ import annotations

import json
import secrets
import socket
import statistics
import subprocess
import sys
import threading
import time
import webbrowser
from io import BytesIO
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
RECEIVER_HOST = "0.0.0.0"
RECEIVER_PORT = 8766
JST = timezone(timedelta(hours=9))
CACHE_TTL_SECONDS = 45
SUMMARY_CACHE: dict[int, tuple[float, dict]] = {}
APP_DIR = Path(__file__).resolve().parent
LOCAL_DATA_DIR = APP_DIR / "local_data"
ANDROID_IMPORT_PATH = LOCAL_DATA_DIR / "android_events.json"
ANDROID_SENDER_PATH = LOCAL_DATA_DIR / "android_sender_events.json"
SENDER_TOKEN_PATH = LOCAL_DATA_DIR / "sender_token.txt"
SENDER_STATUS_PATH = LOCAL_DATA_DIR / "sender_status.json"
IMPORT_SOURCES_PATH = LOCAL_DATA_DIR / "import_sources.json"
IMPORT_STATE_PATH = LOCAL_DATA_DIR / "import_state.json"


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


def read_json_file(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def load_imported_android_events() -> list[dict]:
    data = read_json_file(ANDROID_IMPORT_PATH, [])
    return data if isinstance(data, list) else []


def load_sender_android_events() -> list[dict]:
    data = read_json_file(ANDROID_SENDER_PATH, [])
    return data if isinstance(data, list) else []


def get_sender_token() -> str:
    LOCAL_DATA_DIR.mkdir(exist_ok=True)
    if SENDER_TOKEN_PATH.exists():
        token = SENDER_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    SENDER_TOKEN_PATH.write_text(token, encoding="utf-8")
    return token


def is_private_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return False
    if nums[0] == 10:
        return True
    if nums[0] == 172 and 16 <= nums[1] <= 31:
        return True
    if nums[0] == 192 and nums[1] == 168:
        return True
    return False


def is_tailscale_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return False
    return nums[0] == 100 and 64 <= nums[1] <= 127


def is_linklocal_ipv4(value: str) -> bool:
    return value.startswith("169.254.")


def detect_ipv4_candidates() -> list[dict]:
    seen = set()
    results: list[dict] = []

    def add(ip: str, source: str, interface: str = ""):
        ip = ip.strip()
        if not ip or ip.startswith("127.") or is_linklocal_ipv4(ip) or ip in seen:
            return
        seen.add(ip)
        if is_tailscale_ipv4(ip):
            kind = "tailscale"
            priority = 0
        elif is_private_ipv4(ip):
            kind = "lan"
            priority = 1
        else:
            kind = "network"
            priority = 2
        results.append({"ip": ip, "type": kind, "source": source, "interface": interface, "priority": priority})

    try:
        ps = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object { $_.IPAddress -notlike '127.*' -and $_.AddressState -ne 'Deprecated' } | "
                "Select-Object InterfaceAlias,IPAddress | ConvertTo-Json -Compress",
            ],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
        data = json.loads(ps) if ps.strip() else []
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    add(str(item.get("IPAddress") or ""), "Get-NetIPAddress", str(item.get("InterfaceAlias") or ""))
    except Exception:
        pass

    try:
        ipconfig = subprocess.check_output(["ipconfig"], text=True, encoding="utf-8", errors="ignore", timeout=5)
        current_interface = ""
        for line in ipconfig.splitlines():
            stripped = line.strip()
            if stripped.endswith(":") and "adapter" in stripped.lower():
                current_interface = stripped.rstrip(":")
            if "IPv4" not in line:
                continue
            ip = line.split(":")[-1].strip()
            add(ip, "ipconfig", current_interface)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add(info[4][0], "hostname")
    except Exception:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        add(sock.getsockname()[0], "default-route")
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass

    return sorted(results, key=lambda item: (item["priority"], item["ip"]))


def get_pairing_host() -> str:
    override = LOCAL_DATA_DIR / "pairing_host.txt"
    if override.exists():
        value = override.read_text(encoding="utf-8").strip()
        if value:
            return value
    candidates = [item["ip"] for item in detect_ipv4_candidates()]
    for ip in candidates:
        if is_private_ipv4(ip):
            return ip
    for ip in candidates:
        if is_tailscale_ipv4(ip):
            return ip
    if candidates:
        return candidates[0]
    return "127.0.0.1"


def get_pairing_payload() -> dict:
    endpoints = [
        {
            "type": item["type"],
            "url": f"http://{item['ip']}:{RECEIVER_PORT}",
            "host": item["ip"],
            "interface": item.get("interface", ""),
            "priority": item["priority"],
        }
        for item in detect_ipv4_candidates()
    ]
    if not endpoints:
        endpoints.append({"type": "localhost", "url": f"http://127.0.0.1:{RECEIVER_PORT}", "host": "127.0.0.1", "priority": 9})
    primary = endpoints[0]["url"]
    return {
        "name": "PC Lifelog Stats",
        "server": primary,
        "endpoints": endpoints,
        "token": get_sender_token(),
        "version": 1,
        "once": True,
    }


def normalize_sender_event(event: dict) -> dict | None:
    timestamp = event.get("timestamp")
    if not timestamp:
        return None
    try:
        duration_value = max(0.0, float(event.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration_value = 0.0
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    app = data.get("app") or data.get("appLabel") or data.get("package") or "Android"
    package = data.get("package") or data.get("packageName") or ""
    classname = data.get("classname") or data.get("className") or ""
    return {
        "timestamp": timestamp,
        "duration": duration_value,
        "data": {
            "app": app,
            "package": package,
            "classname": classname,
            "source": "android-sender",
        },
    }


def event_key(event: dict):
    data = event.get("data") or {}
    return (
        event.get("timestamp"),
        round(float(event.get("duration") or 0.0), 3),
        data.get("app"),
        data.get("package"),
        data.get("classname"),
    )


def save_sender_events(incoming: list[dict]) -> dict:
    existing = load_sender_android_events()
    merged = {event_key(event): event for event in existing if isinstance(event, dict)}
    accepted = 0
    for event in incoming:
        normalized = normalize_sender_event(event)
        if not normalized:
            continue
        key = event_key(normalized)
        if key not in merged:
            accepted += 1
        merged[key] = normalized
    events = sorted(merged.values(), key=lambda item: item.get("timestamp") or "")
    LOCAL_DATA_DIR.mkdir(exist_ok=True)
    ANDROID_SENDER_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    status = {
        "last_received_at": datetime.now(JST).isoformat(timespec="seconds"),
        "total_events": len(events),
        "accepted_events": accepted,
    }
    SENDER_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_CACHE.clear()
    return status


def get_sender_status() -> dict:
    status = read_json_file(SENDER_STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    status["configured"] = SENDER_TOKEN_PATH.exists()
    status["events"] = len(load_sender_android_events())
    status["receiver"] = get_pairing_payload()["server"]
    status["endpoints"] = get_pairing_payload()["endpoints"]
    return status


def minutes_since_iso(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return max(0, int((datetime.now(JST) - dt.astimezone(JST)).total_seconds() // 60))


def refresh_android_imports_if_needed() -> dict:
    if not IMPORT_SOURCES_PATH.exists():
        return {"enabled": False, "updated": False, "sources": 0}
    try:
        config = json.loads(IMPORT_SOURCES_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"enabled": False, "updated": False, "sources": 0}

    source_paths = [Path(path) for path in config.get("paths", []) if isinstance(path, str)]
    existing = [path for path in source_paths if path.exists()]
    if not existing:
        return {"enabled": True, "updated": False, "sources": 0}

    signature = {
        str(path): {"mtime": path.stat().st_mtime, "size": path.stat().st_size}
        for path in existing
    }
    previous = {}
    if IMPORT_STATE_PATH.exists():
        try:
            previous = json.loads(IMPORT_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    if previous.get("signature") == signature and ANDROID_IMPORT_PATH.exists():
        return {"enabled": True, "updated": False, "sources": len(existing)}

    try:
        from import_android_export import import_sources

        count, total_seconds = import_sources(existing)
    except Exception:
        return {"enabled": True, "updated": False, "sources": len(existing), "error": True}

    IMPORT_STATE_PATH.write_text(
        json.dumps(
            {
                "signature": signature,
                "last_imported_at": datetime.now(JST).isoformat(timespec="seconds"),
                "events": count,
                "hours": round(total_seconds / 3600, 2),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    SUMMARY_CACHE.clear()
    return {"enabled": True, "updated": True, "sources": len(existing), "events": count}


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


def event_interval(event: dict) -> tuple[datetime, datetime] | None:
    start = parse_aw_time(event.get("timestamp"))
    seconds = duration(event)
    if not start or seconds <= 0:
        return None
    start_local = start.astimezone(JST)
    return start_local, start_local + timedelta(seconds=seconds)


def clipped_interval(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> tuple[datetime, datetime] | None:
    clipped_start = max(start, window_start)
    clipped_end = min(end, window_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def interval_seconds(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def round_minutes(seconds: float) -> float:
    return round(seconds / 60, 1)


def round_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def median(values: list[float]) -> float:
    clean = [v for v in values if v > 0]
    return statistics.median(clean) if clean else 0.0


def build_focus_lab(activity_events: list[dict], pc_seconds: float, android_seconds: float, hourly_seconds: list[float]) -> dict:
    events = sorted(
        [event for event in activity_events if event.get("duration", 0) >= 10 and event.get("start")],
        key=lambda item: item["start"],
    )
    total_seconds = pc_seconds + android_seconds
    if total_seconds <= 0:
        return {
            "score": 0,
            "grade": "NO DATA",
            "confidence": "LOW",
            "summary": "まだ分析できるだけの画面時間がありません。",
            "deepWorkMinutes": 0,
            "longestBlockMinutes": 0,
            "contextSwitches": 0,
            "switchesPerHour": 0,
            "androidShare": 0,
            "nightShare": 0,
            "analyzedEvents": 0,
            "cards": [],
            "scoreBreakdown": [],
            "recommendations": ["ActivityWatchとAndroid Senderが動くと、ここに集中度の読み解きが出ます。"],
        }

    blocks = []
    current = None
    for event in events:
        start = event["start"]
        duration_seconds = float(event.get("duration") or 0.0)
        end = start + timedelta(seconds=duration_seconds)
        label = str(event.get("label") or "unknown")
        source = str(event.get("source") or "pc")
        if current and current["label"] == label and current["source"] == source and (start - current["end"]).total_seconds() <= 300:
            current["end"] = max(current["end"], end)
            current["seconds"] += duration_seconds
        else:
            current = {"label": label, "source": source, "start": start, "end": end, "seconds": duration_seconds}
            blocks.append(current)

    context_switches = 0
    for previous, current_block in zip(blocks, blocks[1:]):
        gap = (current_block["start"] - previous["end"]).total_seconds()
        if gap <= 300 and previous["seconds"] >= 60 and current_block["seconds"] >= 60:
            context_switches += 1

    pc_blocks = [block for block in blocks if block["source"] == "pc"]
    deep_blocks = [block for block in pc_blocks if block["seconds"] >= 25 * 60]
    deep_work_seconds = sum(block["seconds"] for block in deep_blocks)
    longest_block_seconds = max([block["seconds"] for block in blocks] or [0.0])
    active_hours = max(total_seconds / 3600, 0.1)
    pc_hours = max(pc_seconds / 3600, 0.1)
    switches_per_hour = context_switches / active_hours
    android_share = android_seconds / total_seconds if total_seconds else 0.0
    night_seconds = sum(hourly_seconds[21:24])
    night_share = night_seconds / total_seconds if total_seconds else 0.0
    deep_ratio = deep_work_seconds / pc_seconds if pc_seconds else 0.0

    switch_penalty = min(22, switches_per_hour * 3)
    android_penalty = min(20, max(0.0, android_share - 0.15) * 45)
    night_penalty = min(16, max(0.0, night_share - 0.22) * 45)
    deep_bonus = min(18, deep_ratio * 35)
    score = 72 + deep_bonus - switch_penalty - android_penalty - night_penalty
    score = int(round(clamp(score, 0, 100)))
    confidence = "HIGH" if total_seconds >= 3 * 3600 and len(events) >= 40 else ("MED" if total_seconds >= 3600 and len(events) >= 12 else "LOW")

    if score >= 82:
        grade = "DEEP"
        summary = "かなり集中寄り。画面時間が作業の形になっています。"
    elif score >= 64:
        grade = "STEADY"
        summary = "悪くない安定感。切り替えを少し減らすともっと伸びます。"
    elif score >= 42:
        grade = "SCATTERED"
        summary = "やや散らかり気味。スマホ比率かアプリ切り替えが集中を削っています。"
    else:
        grade = "DRIFT"
        summary = "流されやすい日。まずは短い集中ブロックを一つ作るのが良さそうです。"

    recommendations = []
    if switches_per_hour >= 8:
        recommendations.append("アプリ切り替えが多め。25分だけ主役アプリを一つに絞ると見え方が変わります。")
    if android_share >= 0.35:
        recommendations.append("Android比率が高め。スマホを見る前にPC側で目的を一行だけ決めると吸われにくいです。")
    if night_share >= 0.28:
        recommendations.append("夜の画面時間が濃いです。21時以降のピークを一段薄くできると睡眠側に効きます。")
    if deep_ratio < 0.18 and pc_seconds / 60 >= 60:
        recommendations.append("PC時間のわりに25分以上の塊が少なめ。通知を切った短い作業島を作る価値があります。")
    if not recommendations:
        recommendations.append("今日の形はかなり良いです。このリズムを週単位で見られるようにすると強いです。")

    return {
        "score": score,
        "grade": grade,
        "confidence": confidence,
        "summary": summary,
        "deepWorkMinutes": round_minutes(deep_work_seconds),
        "longestBlockMinutes": round_minutes(longest_block_seconds),
        "contextSwitches": context_switches,
        "switchesPerHour": round(switches_per_hour, 1),
        "androidShare": round(android_share * 100, 1),
        "nightShare": round(night_share * 100, 1),
        "analyzedEvents": len(events),
        "scoreBreakdown": [
            {"label": "Base", "value": "+72", "note": "ふつうの日の出発点"},
            {"label": "Deep Work", "value": f"+{round(deep_bonus, 1)}", "note": "25分以上の塊で加点"},
            {"label": "Switching", "value": f"-{round(switch_penalty, 1)}", "note": "意味のある切り替えで減点"},
            {"label": "Android Pull", "value": f"-{round(android_penalty, 1)}", "note": "スマホ比率が15%を超えた分"},
            {"label": "Night Drift", "value": f"-{round(night_penalty, 1)}", "note": "21時以降が22%を超えた分"},
        ],
        "cards": [
            {"label": "Deep Work", "value": f"{round_minutes(deep_work_seconds)}m", "sub": "25分以上のPC集中ブロック"},
            {"label": "Switching", "value": f"{context_switches}", "sub": f"1時間あたり {round(switches_per_hour, 1)} 回"},
            {"label": "Android Pull", "value": f"{round(android_share * 100, 1)}%", "sub": "全画面時間に占めるスマホ比率"},
            {"label": "Night Drift", "value": f"{round(night_share * 100, 1)}%", "sub": "21時以降に寄った割合"},
        ],
        "recommendations": recommendations[:3],
    }


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


def split_by_day(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        next_day = datetime(cursor.year, cursor.month, cursor.day, tzinfo=JST) + timedelta(days=1)
        chunk_end = min(end, next_day)
        yield cursor, chunk_end
        cursor = chunk_end


def split_by_hour(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        chunk_end = min(end, next_hour)
        yield cursor, chunk_end
        cursor = chunk_end


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
    import_status = refresh_android_imports_if_needed()
    cached = SUMMARY_CACHE.get(days)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        data = dict(cached[1])
        data["cached"] = True
        return data

    buckets = aw_get("/buckets")
    groups = pick_buckets(buckets)
    android_bridge_buckets = get_android_bridge_buckets()
    groups["android_bridge"] = android_bridge_buckets
    imported_android_events = load_imported_android_events()
    sender_android_events = load_sender_android_events()
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
    activity_timeline: list[dict] = []
    today_events = []

    def usage_for(dt: datetime) -> dict:
        key = dt.strftime("%Y-%m-%d")
        if key not in usage_by_date:
            usage_by_date[key] = empty_usage()
        return usage_by_date[key]

    def add_usage_span(start: datetime, end: datetime, key: str):
        for chunk_start, chunk_end in split_by_day(start, end):
            usage_for(chunk_start)[key] += interval_seconds(chunk_start, chunk_end)

    def add_hourly_span(start: datetime, end: datetime):
        for chunk_start, chunk_end in split_by_hour(start, end):
            hourly_seconds[chunk_start.hour] += interval_seconds(chunk_start, chunk_end)

    def record_event(event: dict, usage_key: str, source: str, label_prefix: str = "", include_title: bool = False):
        interval = event_interval(event)
        if not interval:
            return
        event_start, event_end = interval
        visible = clipped_interval(event_start, event_end, fetch_start, today_end)
        if not visible:
            return
        visible_start, visible_end = visible
        visible_seconds = interval_seconds(visible_start, visible_end)
        add_usage_span(visible_start, visible_end, usage_key)

        selected = clipped_interval(event_start, event_end, selected_start, selected_end)
        if selected:
            selected_start_clip, selected_end_clip = selected
            selected_seconds = interval_seconds(selected_start_clip, selected_end_clip)
            label = event_label(event, source)
            app_label = f"{label_prefix}{label}" if label_prefix else label
            app_seconds[app_label] = app_seconds.get(app_label, 0.0) + selected_seconds
            if include_title:
                title = event_title(event)
                if title:
                    title_seconds[title] = title_seconds.get(title, 0.0) + selected_seconds
            add_hourly_span(selected_start_clip, selected_end_clip)
            activity_timeline.append(
                {
                    "start": selected_start_clip,
                    "duration": selected_seconds,
                    "label": label,
                    "source": source,
                }
            )

        today_overlap = clipped_interval(event_start, event_end, today_start, today_end)
        if today_overlap:
            display_event = dict(event)
            display_event["timestamp"] = today_overlap[0].isoformat()
            display_event["duration"] = interval_seconds(today_overlap[0], today_overlap[1])
            today_events.append(display_event)

    for bucket_id in groups["window"] + groups["web"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            record_event(event, "window", "pc", include_title=True)

    for bucket_id in groups["afk"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            if (event.get("data") or {}).get("status") != "not-afk":
                continue
            interval = event_interval(event)
            if not interval:
                continue
            visible = clipped_interval(interval[0], interval[1], fetch_start, today_end)
            if visible:
                add_usage_span(visible[0], visible[1], "active")

    for bucket_id in groups["android"]:
        for event in fetch_events(bucket_id, fetch_start, today_end):
            record_event(event, "android", "android", label_prefix="Android: ")

    for bucket_id in groups["android_bridge"]:
        for event in fetch_events(bucket_id, fetch_start, today_end, base=ANDROID_AW_BASE):
            record_event(event, "android", "android", label_prefix="Android: ")

    for event in imported_android_events:
        record_event(event, "android", "android", label_prefix="Android: ")

    for event in sender_android_events:
        record_event(event, "android", "android", label_prefix="Android: ")

    daily = []
    total_window_seconds = 0.0
    total_afk_active_seconds = 0.0
    total_android_seconds = 0.0
    sender_period_seconds = 0.0
    sender_today_seconds = 0.0

    for event in sender_android_events:
        interval = event_interval(event)
        if not interval:
            continue
        selected = clipped_interval(interval[0], interval[1], selected_start, selected_end)
        if selected:
            sender_period_seconds += interval_seconds(selected[0], selected[1])
        today_overlap = clipped_interval(interval[0], interval[1], today_start, today_end)
        if today_overlap:
            sender_today_seconds += interval_seconds(today_overlap[0], today_overlap[1])

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
    sender_status = get_sender_status()
    sender_status["minutesSinceLastReceived"] = minutes_since_iso(sender_status.get("last_received_at"))
    total_pc_seconds = max(total_window_seconds, total_afk_active_seconds)
    total_screen_seconds = total_pc_seconds + total_android_seconds

    result = {
        "ok": True,
        "cached": False,
        "generatedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "days": days,
        "buckets": groups,
        "hasAndroid": bool(groups["android"] or groups["android_bridge"] or imported_android_events or sender_android_events),
        "androidBridgeUrl": ANDROID_AW_BASE,
        "importedAndroidEvents": len(imported_android_events),
        "senderAndroidEvents": len(sender_android_events),
        "senderStatus": sender_status,
        "androidImportStatus": import_status,
        "stats": {
            "todayHours": daily[-1]["totalHours"] if daily else 0,
            "periodTotalHours": round(sum(daily_totals), 2),
            "averageHours": round(sum(daily_totals) / len(daily_totals), 2) if daily_totals else 0,
            "medianHours": round(median(daily_totals), 2),
            "maxHours": round(max(daily_totals), 2) if daily_totals else 0,
            "pcWindowHours": round_hours(total_window_seconds),
            "pcActiveHours": round_hours(total_afk_active_seconds),
            "androidHours": round_hours(total_android_seconds),
            "pcHours": round_hours(total_pc_seconds),
            "screenHours": round_hours(total_screen_seconds),
            "senderTodayHours": round_hours(sender_today_seconds),
            "senderPeriodHours": round_hours(sender_period_seconds),
        },
        "focusLab": build_focus_lab(activity_timeline, total_pc_seconds, total_android_seconds, hourly_seconds),
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
    .focus-lab { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 18px; align-items: stretch; }
    .score-dial {
      border-radius: 8px;
      background: linear-gradient(155deg, #0f172a, #0f766e);
      color: #f8fafc;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 210px;
    }
    .score-dial .label { color: rgba(248,250,252,.72); }
    .score { font-size: 62px; line-height: .95; font-weight: 850; letter-spacing: 0; }
    .grade { display: inline-flex; align-self: flex-start; padding: 5px 9px; border-radius: 999px; background: rgba(255,255,255,.14); font-size: 12px; font-weight: 800; }
    .focus-copy { display: flex; flex-direction: column; gap: 12px; }
    .focus-summary { font-size: 17px; font-weight: 750; line-height: 1.6; }
    .score-meta { color: var(--muted); font-size: 12px; }
    .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f8fafc;
      padding: 11px;
      min-height: 86px;
    }
    .metric strong { display: block; font-size: 24px; margin: 5px 0 3px; }
    .actions { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
    .actions li { border-left: 3px solid var(--accent); padding: 7px 10px; background: #f8fafc; border-radius: 6px; color: #334155; }
    .breakdown {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }
    .breakdown-item { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #ffffff; }
    .breakdown-item strong { display: block; font-size: 17px; margin-bottom: 3px; }
    .breakdown-item span { display: block; color: var(--muted); font-size: 11px; line-height: 1.35; }
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
    .pairing { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 16px; align-items: center; }
    .pairing-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .connection-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 10px 0 12px; }
    .connection-pill { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #f8fafc; }
    .connection-pill.ok { border-color: rgba(15,118,110,.35); background: #ecfdf5; }
    .connection-pill strong { display: block; font-size: 18px; margin-top: 4px; }
    .connection-pill .mini { color: var(--muted); font-size: 11px; margin-top: 4px; line-height: 1.35; }
    .qr-box { display: none; justify-self: end; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    .qr-box.visible { display: block; }
    .qr-box img { display: block; width: 190px; height: 190px; }
    .mono { font-family: Consolas, "SFMono-Regular", monospace; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
    .endpoint-list { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
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
      .focus-lab { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(2, 1fr); }
      .breakdown { grid-template-columns: repeat(2, 1fr); }
      .pairing { grid-template-columns: 1fr; }
      .connection-row { grid-template-columns: 1fr; }
      .qr-box { justify-self: start; }
    }
    @media (max-width: 520px) {
      main { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
      .value { font-size: 28px; }
      .metric-grid { grid-template-columns: 1fr; }
      .breakdown { grid-template-columns: 1fr; }
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
    <section class="panel">
      <div class="panel-head">
        <h2>Focus Lab</h2>
        <div class="hint">時間の量ではなく、画面時間の質を見る</div>
      </div>
      <div class="focus-lab">
        <div class="score-dial">
          <div>
            <div class="label">Focus Score</div>
            <div class="score" id="focusScore">--</div>
          </div>
          <div class="grade" id="focusGrade">--</div>
        </div>
        <div class="focus-copy">
          <div class="focus-summary" id="focusSummary">分析中...</div>
          <div class="score-meta" id="focusMeta"></div>
          <div class="metric-grid" id="focusCards"></div>
          <div class="breakdown" id="focusBreakdown"></div>
          <ul class="actions" id="focusActions"></ul>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <h2>Android連携</h2>
        <div class="hint">QRは初回だけ。読み込んだらスマホ側に保存されます。</div>
      </div>
      <div class="pairing">
        <div>
          <div id="senderSummary" class="sub">接続状態を確認中...</div>
          <div class="connection-row">
            <div class="connection-pill" id="senderConnectionPill"><div class="label">接続</div><strong id="senderConnection">--</strong></div>
            <div class="connection-pill"><div class="label">今日の自動送信分</div><strong id="senderToday">--</strong></div>
            <div class="connection-pill"><div class="label">Android合計</div><strong id="androidTotal">--</strong></div>
            <div class="connection-pill"><div class="label">自動同期</div><strong id="androidSyncMode">Wi-Fi</strong><div class="mini" id="androidSyncHint">おおむね15分ごと</div></div>
          </div>
          <div id="senderUrl" class="mono"></div>
          <div id="senderEndpoints" class="endpoint-list mono"></div>
          <div class="pairing-actions">
            <button id="showQr">接続QRを表示</button>
            <button id="hideQr">QRを隠す</button>
          </div>
        </div>
        <div class="qr-box" id="qrBox">
          <img id="qrImage" alt="Android pairing QR">
        </div>
      </div>
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
      renderFocusLab(data.focusLab || {});
      renderSender(data);
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

    function renderFocusLab(focus) {
      document.getElementById('focusScore').textContent = focus.score ?? '--';
      document.getElementById('focusGrade').textContent = focus.grade || '--';
      document.getElementById('focusSummary').textContent = focus.summary || 'まだ分析できるだけのデータがありません。';
      document.getElementById('focusMeta').textContent = `信頼度 ${focus.confidence || 'LOW'} / 分析イベント ${focus.analyzedEvents ?? 0} 件`;
      const cards = Array.isArray(focus.cards) ? focus.cards : [];
      document.getElementById('focusCards').innerHTML = cards.map(card => `
        <div class="metric">
          <div class="label">${esc(card.label)}</div>
          <strong>${esc(card.value)}</strong>
          <div class="sub">${esc(card.sub)}</div>
        </div>
      `).join('');
      const breakdown = Array.isArray(focus.scoreBreakdown) ? focus.scoreBreakdown : [];
      document.getElementById('focusBreakdown').innerHTML = breakdown.map(item => `
        <div class="breakdown-item">
          <strong>${esc(item.value)}</strong>
          <div>${esc(item.label)}</div>
          <span>${esc(item.note)}</span>
        </div>
      `).join('');
      const actions = Array.isArray(focus.recommendations) ? focus.recommendations : [];
      document.getElementById('focusActions').innerHTML = actions.map(action => `<li>${esc(action)}</li>`).join('');
    }

    function renderSender(data) {
      const status = data.senderStatus || {};
      const mins = status.minutesSinceLastReceived;
      const fresh = typeof mins === 'number' && mins <= 30;
      const last = status.last_received_at ? `最終受信 ${status.last_received_at.replace('T', ' ')} (${mins}分前)` : 'まだSenderからの受信なし';
      const events = Number(data.senderAndroidEvents || 0);
      document.getElementById('senderSummary').textContent = `Senderイベント ${events}件 / ${last}`;
      document.getElementById('senderConnection').textContent = fresh ? 'ONLINE' : (events > 0 ? '受信あり' : '未接続');
      document.getElementById('senderConnectionPill').classList.toggle('ok', fresh || events > 0);
      document.getElementById('senderToday').textContent = fmtHours(data.stats.senderTodayHours || 0);
      document.getElementById('androidTotal').textContent = fmtHours(data.stats.androidHours || 0);
      const nextHint = typeof mins === 'number' && mins <= 60 ? `前回から${mins}分 / 15分目安` : 'Wi-Fi接続時に自動送信';
      document.getElementById('androidSyncHint').textContent = nextHint;
      document.getElementById('senderUrl').textContent = status.receiver ? `優先受信先: ${status.receiver}` : '';
      const endpoints = Array.isArray(status.endpoints) ? status.endpoints : [];
      document.getElementById('senderEndpoints').innerHTML = endpoints.map(ep =>
        `<div>${esc(ep.type || 'endpoint')}: ${esc(ep.url || '')}</div>`
      ).join('');
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
    document.getElementById('showQr').addEventListener('click', () => {
      document.getElementById('qrImage').src = `/api/android/pairing-qr?t=${Date.now()}`;
      document.getElementById('qrBox').classList.add('visible');
    });
    document.getElementById('hideQr').addEventListener('click', () => {
      document.getElementById('qrBox').classList.remove('visible');
    });
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
        if parsed.path == "/api/android/pairing":
            self.send_json({"ok": True, "pairing": get_pairing_payload()})
            return
        if parsed.path == "/api/android/status":
            self.send_json({"ok": True, "status": get_sender_status()})
            return
        if parsed.path == "/api/android/ping":
            qs = parse_qs(parsed.query)
            token = (qs.get("token") or [""])[0] or self.headers.get("X-PC-Lifelog-Token", "")
            if not secrets.compare_digest(token, get_sender_token()):
                self.send_json({"ok": False, "message": "unauthorized"}, status=401)
                return
            self.send_json(
                {
                    "ok": True,
                    "name": "PC Lifelog Stats",
                    "time": datetime.now(JST).isoformat(timespec="seconds"),
                    "receiverPort": RECEIVER_PORT,
                }
            )
            return
        if parsed.path == "/api/android/pairing-qr":
            self.send_qr(get_pairing_payload())
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

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/android/events":
            self.send_json({"ok": False, "message": "not found"}, status=404)
            return
        qs = parse_qs(parsed.query)
        token = (qs.get("token") or [""])[0] or self.headers.get("X-PC-Lifelog-Token", "")
        if not secrets.compare_digest(token, get_sender_token()):
            self.send_json({"ok": False, "message": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 8_000_000:
            self.send_json({"ok": False, "message": "invalid body"}, status=400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"ok": False, "message": "invalid json"}, status=400)
            return
        events = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(events, list):
            self.send_json({"ok": False, "message": "events must be a list"}, status=400)
            return
        status = save_sender_events([event for event in events if isinstance(event, dict)])
        self.send_json({"ok": True, "status": status})

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

    def send_bytes(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_qr(self, payload: dict):
        try:
            import qrcode

            image = qrcode.make(json.dumps(payload, ensure_ascii=False))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            self.send_bytes(buffer.getvalue(), "image/png")
        except Exception as exc:
            self.send_json({"ok": False, "message": f"QR generation failed: {exc}"}, status=500)


def open_browser_later(url: str):
    time.sleep(0.8)
    webbrowser.open(url)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    receiver = ThreadingHTTPServer((RECEIVER_HOST, RECEIVER_PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"PCライフログ統計: {url}")
    print(f"Android Sender receiver: http://{get_pairing_host()}:{RECEIVER_PORT}")
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    if "--no-open" not in sys.argv:
        threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します")
    finally:
        receiver.shutdown()


if __name__ == "__main__":
    main()

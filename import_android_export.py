from __future__ import annotations

import json
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
LOCAL_DATA_DIR = APP_DIR / "local_data"
OUTPUT_PATH = LOCAL_DATA_DIR / "android_events.json"


def load_export(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Export root must be a JSON object")
    return data


def normalize_event(event: dict) -> dict | None:
    timestamp = event.get("timestamp")
    if not timestamp:
        return None
    try:
        duration = max(0.0, float(event.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    app = data.get("app") or data.get("package") or "Android"
    package = data.get("package") or ""
    classname = data.get("classname") or ""
    return {
        "timestamp": timestamp,
        "duration": duration,
        "data": {
            "app": app,
            "package": package,
            "classname": classname,
            "source": "android-export",
        },
    }


def extract_events(export: dict) -> list[dict]:
    buckets = export.get("buckets")
    if not isinstance(buckets, dict):
        raise ValueError("Export does not contain a buckets object")

    normalized = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        bucket_type = str(bucket.get("type") or bucket.get("event_type") or "")
        if "android" not in bucket_id.lower() and bucket_type != "currentwindow":
            continue
        if "unlock" in bucket_id.lower() or "lockscreen" in bucket_type:
            continue
        events = bucket.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if isinstance(event, dict):
                item = normalize_event(event)
                if item:
                    normalized.append(item)

    normalized.sort(key=lambda event: event["timestamp"])
    return normalized


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python import_android_export.py <aw-buckets-export.json>")
        return 2
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.exists():
        print(f"File not found: {source}")
        return 1

    export = load_export(source)
    events = extract_events(export)
    LOCAL_DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    total_seconds = sum(float(event.get("duration") or 0.0) for event in events)
    print(f"Imported Android events: {len(events)}")
    print(f"Total duration: {total_seconds / 3600:.2f}h")
    print(f"Saved local data: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

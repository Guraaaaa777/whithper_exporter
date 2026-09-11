"""時刻まわりのユーティリティ（期間パース・タイムスタンプ解釈・ウィンドウ整列）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# "1h" / "10m" / "90s" / "1d" / "1h30m" のような期間表記
_DURATION_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)")
_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}

FILENAME_STAMP = "%Y%m%d%H%M"


class TimeParseError(ValueError):
    """期間文字列やタイムスタンプの解釈に失敗したとき。"""


def parse_duration(text: str | int | float, allow_zero: bool = False) -> timedelta:
    """"1h" / "10m" / "1h30m" / 3600 を timedelta に変換する。"""
    floor = 0.0 if allow_zero else 1e-9
    if isinstance(text, (int, float)):
        seconds = float(text)
        if seconds < floor:
            raise TimeParseError(f"期間は正の値である必要があります: {text!r}")
        return timedelta(seconds=seconds)

    raw = str(text).strip()
    if not raw:
        raise TimeParseError("期間が空です")

    matches = list(_DURATION_RE.finditer(raw))
    if not matches or "".join(m.group(0) for m in matches).replace(" ", "") != raw.replace(" ", ""):
        raise TimeParseError(f"期間の書式が不正です: {text!r} (例: '1h', '10m', '1h30m')")

    seconds = 0.0
    for match in matches:
        unit = match.group("unit").lower()
        if unit not in _UNITS:
            raise TimeParseError(f"未知の単位です: {unit!r} (使えるのは s/m/h/d)")
        seconds += float(match.group("value")) * _UNITS[unit]

    if seconds < floor:
        raise TimeParseError(f"期間は正の値である必要があります: {text!r}")
    return timedelta(seconds=seconds)


def local_tz() -> timezone:
    """OSのローカルタイムゾーン（固定オフセットとして取得）。"""
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def resolve_tz(name: str | None):
    """設定の timezone 名を tzinfo に変換する。None/"local" ならOS設定を使う。"""
    if name is None or name.lower() in {"local", "localtime", "system"}:
        return local_tz()
    if name.upper() in {"UTC", "Z"}:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
    except ImportError as exc:  # pragma: no cover - Python 3.9+ には必ずある
        raise TimeParseError("zoneinfo が利用できません") from exc
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise TimeParseError(
            f"タイムゾーン {name!r} を解決できません。"
            "Windows では `pip install tzdata` が必要な場合があります"
        ) from exc


def now(tz) -> datetime:
    return datetime.now(tz=tz)


def parse_timestamp(value, tz, fmt: str | None = None) -> datetime:
    """様々な形のタイムスタンプを tz 付き datetime にそろえる。

    対応: datetime / epoch秒 / epochミリ秒 / ISO8601 / 明示 strptime 書式。
    tz を持たない値はすべて tz のローカル時刻とみなす。
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        dt = _from_epoch(float(value), tz)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise TimeParseError("タイムスタンプが空です")
        if fmt:
            dt = datetime.strptime(raw, fmt)
        else:
            dt = _parse_timestamp_string(raw, tz)
    else:
        raise TimeParseError(f"タイムスタンプとして解釈できません: {value!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _from_epoch(value: float, tz) -> datetime:
    # 1e11 を超えるならミリ秒、さらに大きければマイクロ秒とみなす
    if abs(value) >= 1e14:
        value /= 1_000_000
    elif abs(value) >= 1e11:
        value /= 1000
    return datetime.fromtimestamp(value, tz=tz)


_FALLBACK_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y%m%d%H%M%S",
    "%Y%m%d%H%M",
    "%Y-%m-%d",
)


def _parse_timestamp_string(raw: str, tz) -> datetime:
    candidate = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    # 数値だけの文字列は epoch とみなす
    try:
        return _from_epoch(float(raw), tz)
    except ValueError:
        pass
    for fmt in _FALLBACK_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise TimeParseError(f"タイムスタンプを解釈できません: {raw!r}")


def floor_to_interval(dt: datetime, interval: timedelta) -> datetime:
    """その日の 00:00 を基準に interval 単位へ切り下げる。

    interval が1日を超える場合は日単位に切り下げる。
    """
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval >= timedelta(days=1):
        return day_start
    elapsed = dt - day_start
    steps = int(elapsed // interval)
    return day_start + interval * steps


def window_filename(start: datetime, end: datetime, suffix: str = ".txt") -> str:
    """YYYYMMDDhhmm-YYYYMMDDhhmm.txt を組み立てる。"""
    return f"{start.strftime(FILENAME_STAMP)}-{end.strftime(FILENAME_STAMP)}{suffix}"

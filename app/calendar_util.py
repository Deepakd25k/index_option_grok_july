from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import NSE_HOLIDAYS_2026

TZ = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(TZ)


def today_ymd() -> str:
    return now_ist().date().isoformat()


def day_name(ymd: str | None = None) -> str:
    d = date.fromisoformat(ymd) if ymd else now_ist().date()
    return d.strftime("%A")


def now_str() -> str:
    return now_ist().strftime("%Y-%m-%d %H:%M:%S") + " IST"


def trading_status(ymd: str | None = None) -> dict:
    ymd = ymd or today_ymd()
    d = date.fromisoformat(ymd)
    if d.weekday() >= 5:
        return {
            "ymd": ymd,
            "is_trading": False,
            "holiday": "Sunday" if d.weekday() == 6 else "Saturday",
            "reason": "Weekend",
            "day": day_name(ymd),
        }
    h = NSE_HOLIDAYS_2026.get(ymd)
    if h:
        return {
            "ymd": ymd,
            "is_trading": False,
            "holiday": h,
            "reason": "NSE Holiday",
            "day": day_name(ymd),
        }
    return {
        "ymd": ymd,
        "is_trading": True,
        "holiday": "",
        "reason": "",
        "day": day_name(ymd),
    }

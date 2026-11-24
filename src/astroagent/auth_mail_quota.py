"""Reserve SMTP attempts against PostgreSQL-backed, UTC calendar limits."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from astroagent.auth_security import keyed

logger = logging.getLogger(__name__)


class MailQuotaUsage(BaseModel):
    period: Literal["hour", "day", "month"]
    used: int
    limit: int
    resets_at: datetime
    warning: bool


class MailQuotaReached(Exception):
    def __init__(self, resets_at: datetime):
        self.resets_at = resets_at
        super().__init__("SMTP quota reached")


def _windows(settings, now):
    hour = now.replace(minute=0, second=0, microsecond=0)
    day = hour.replace(hour=0)
    month = day.replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    return (
        ("hour", hour, hour + timedelta(hours=1), settings.mail_hour_limit),
        ("day", day, day + timedelta(days=1), settings.mail_day_limit),
        ("month", month, next_month, settings.mail_month_limit),
    )


def reserve_mail_slot(store):
    warnings = []
    with store.connect() as db:
        for period, start, end, limit in _windows(store.settings, datetime.now(UTC)):
            key = keyed(store.settings, "mail-quota", period)
            row = db.execute(
                """
                INSERT INTO public.auth_rates(key,bucket,hits,expires_at) VALUES (%s,%s,1,%s)
                ON CONFLICT (key,bucket) DO UPDATE SET hits=auth_rates.hits+1
                WHERE auth_rates.hits < %s RETURNING hits
                """,
                (key, int(start.timestamp()), end, limit),
            ).fetchone()
            if row is None:
                raise MailQuotaReached(end)
            if row["hits"] == (4 * limit + 4) // 5:
                warnings.append(period)
    for period in warnings:
        logger.warning("SMTP sending quota reached 80%% of the %s limit", period)


def mail_quota_usage(store):
    usage = []
    with store.connect() as db:
        for period, start, end, limit in _windows(store.settings, datetime.now(UTC)):
            key = keyed(store.settings, "mail-quota", period)
            row = db.execute(
                "SELECT hits FROM public.auth_rates WHERE key=%s AND bucket=%s",
                (key, int(start.timestamp())),
            ).fetchone()
            used = row["hits"] if row else 0
            usage.append(
                MailQuotaUsage(
                    period=period,
                    used=used,
                    limit=limit,
                    resets_at=end,
                    warning=used * 5 >= 4 * limit,
                )
            )
    return usage

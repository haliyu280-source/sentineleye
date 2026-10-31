from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Metric

RANGES = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(hours=24), "7d": timedelta(days=7)}

# Charts never need more points than this; longer ranges are averaged into equal time buckets
MAX_POINTS = 360


def metric_history(db: Session, server_id: int, range_key: str, now: datetime) -> dict:
    start = now - RANGES[range_key]
    rows = db.execute(
        select(Metric.collected_at, Metric.cpu_percent, Metric.memory_percent, Metric.disk_percent)
        .where(Metric.server_id == server_id, Metric.collected_at >= start)
        .order_by(Metric.collected_at)
    ).all()

    if len(rows) <= MAX_POINTS:
        points = [{"t": t, "cpu": c, "memory": m, "disk": d, "samples": 1} for t, c, m, d in rows]
        bucket_seconds = None
    else:
        bucket_seconds = max(1, int(RANGES[range_key].total_seconds() // MAX_POINTS))
        buckets: dict[int, list] = {}
        for t, c, m, d in rows:
            index = int((t - start).total_seconds() // bucket_seconds)
            buckets.setdefault(index, []).append((c, m, d))
        points = []
        for index in sorted(buckets):
            values = buckets[index]
            n = len(values)
            points.append(
                {
                    "t": start + timedelta(seconds=index * bucket_seconds),
                    "cpu": round(sum(v[0] for v in values) / n, 2),
                    "memory": round(sum(v[1] for v in values) / n, 2),
                    "disk": round(sum(v[2] for v in values) / n, 2),
                    "samples": n,
                }
            )

    return {
        "server_id": server_id,
        "range": range_key,
        "start": start,
        "end": now,
        "raw_samples": len(rows),
        "bucket_seconds": bucket_seconds,
        "points": points,
    }

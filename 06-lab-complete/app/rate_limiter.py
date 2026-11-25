"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung,
    vẫn còn sau khi restart agent
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Không lưu API key gốc trong Redis — chỉ lưu hash.
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    limit = settings.rate_limit_per_minute

    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)  # bỏ request cũ hơn 60s
    pipe.zcard(bucket)                                       # đếm request trong cửa sổ
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = WINDOW_SECONDS
        if oldest:
            retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {WINDOW_SECONDS}s",
            headers={"Retry-After": str(retry_after)},
        )

    pipe = r.pipeline()
    pipe.zadd(bucket, {f"{now}:{uuid.uuid4().hex}": now})
    pipe.expire(bucket, WINDOW_SECONDS)
    pipe.execute()

"""
Production AI Agent — Part 6 Final Project.

Kiểm tra:  python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(settings.log_level.upper())
logger.propagate = False


def log(event: str, level: int = logging.INFO, **fields):
    logger.log(level, event, extra={"extra_fields": fields})


# ── Graceful shutdown (tiêu chí 11) ──
# Uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` của lifespan và thoát với exit code 0.
# Ta không tự đăng ký signal handler để khỏi đè handler của uvicorn.
_state = {"shutting_down": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute)
    yield
    _state["shutting_down"] = True
    log("shutdown", reason="SIGTERM / lifespan shutdown")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # lỗi không lường trước → 500 gọn, không lộ stack trace ra client
        log("unhandled_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    log("request", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - start) * 1000, 1))
    return response


# ── Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace ──
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request body", "errors": errors})


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, exc: redis.RedisError):
    log("redis_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Storage backend unavailable"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


# ── Liveness (tiêu chí 4): luôn 200 khi process còn chạy, không phụ thuộc Redis ──
@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


# ── Readiness (tiêu chí 5): 503 khi Redis không kết nối được hoặc đang tắt ──
@app.get("/ready")
def ready():
    if _state["shutting_down"]:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not_ready", "redis": "down"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # tiêu chí 7 → 429
    check_budget()                     # tiêu chí 8 → 402
    answer = llm_ask(body.question)
    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    log("ask", user_id=body.user_id, q_len=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}

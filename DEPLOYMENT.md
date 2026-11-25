# Deployment Information

> Agent được deploy là agent Part 6 trong `06-lab-complete/` (`check_production_ready.py`: PASS 12/12), kèm Redis (Render Key Value) trên cùng nền tảng.

## Public URL

https://day14-agent-6q0z.onrender.com

## Platform

**Render** — Blueprint từ `06-lab-complete/render.yaml`, gói Free:

| Resource | Loại | Vai trò |
|---|---|---|
| `day14-agent` | Web Service, runtime Docker, `rootDir: 06-lab-complete` | Agent FastAPI, build bằng `Dockerfile` multi-stage, health check `/health` |
| `day14-redis` | Key Value (Redis), `ipAllowList: []` | State của rate limiter và cost guard; chỉ service nội bộ Render truy cập được |

## Cách deploy

1. Push code lên GitHub (repo public).
2. Render Dashboard → **New +** → **Blueprint** → chọn repo, branch `main`.
3. **Blueprint Path:** `06-lab-complete/render.yaml` (file không nằm ở gốc repo).
4. Nhập giá trị cho `AGENT_API_KEY` khi được hỏi (biến khai báo `sync: false` nên giá trị không nằm trong repo).
5. **Deploy Blueprint** → Render tạo `day14-redis`, build image và chạy `day14-agent`, nối `REDIS_URL` tự động qua `fromService` (`property: connectionString`).

## Test Commands

```bash
BASE=https://day14-agent-6q0z.onrender.com
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả thực tế (25/11/2026):

```
/health                 → 200   {"status":"ok","environment":"production"}
/ready                  → 200   {"status":"ready","redis":"ok"}
/ask không có key       → 401
/ask sai key            → 401   {"detail":"Missing or invalid API key"}
/ask có key đúng        → 200   {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."}
```

`/ready` trả `"redis":"ok"` xác nhận agent đã kết nối được Redis trên Render (readiness ping Redis, Redis lỗi thì trả 503).

Kiểm tra bằng script chấm:

```
$ python check_production_ready.py --static-only --public-url https://day14-agent-6q0z.onrender.com
✅ 12. Public URL ready (Railway / Render config)
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://day14-agent-6q0z.onrender.com/health → 200
```

Rate limit (giới hạn `RATE_LIMIT_PER_MINUTE=10`, state trong Redis):

```bash
for i in $(seq 1 12); do curl -sS -o /dev/null -w "$i: %{http_code}\n" -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'; done
```

```
1: 200
2: 200
3: 200
4: 200
5: 200
6: 200
7: 200
8: 200
9: 200
10: 429
11: 429
12: 429

$ curl -i ... (request tiếp theo)
HTTP/1.1 429 Too Many Requests
retry-after: 51
{"detail":"Rate limit exceeded: 10 requests per 60s"}
```

Request "có key" ngay trước vòng lặp đã tính 1 lượt, nên đúng 10 request thành công trong 60 giây rồi bị chặn 429 kèm `Retry-After`.

> Lưu ý gói Free: web service tự tắt sau 15 phút không có request, request đầu tiên sau đó mất ~1 phút để khởi động lại. Nếu lệnh đầu bị chậm/timeout, gọi lại `/health` rồi chạy tiếp.

## Environment Variables Set

| Biến | Nguồn |
|---|---|
| `PORT` | Render tự cấp (10000); `CMD` của Dockerfile lắng nghe `${PORT:-8000}` |
| `REDIS_URL` | `fromService` → connection string nội bộ của `day14-redis` |
| `AGENT_API_KEY` | Nhập trên dashboard lúc tạo Blueprint (`sync: false`), không có trong repo |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` | `1.0` / `10.0` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

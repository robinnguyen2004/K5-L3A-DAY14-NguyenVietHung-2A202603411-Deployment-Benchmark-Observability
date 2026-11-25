# Deployment Information

> Agent được deploy là agent Part 6 trong `06-lab-complete/` (PASS 12/12), kèm Redis trên cùng nền tảng.

## Public URL

<!-- TODO(bạn): dán URL sau khi deploy, vd https://day14-agent-production.up.railway.app -->
https://YOUR-AGENT-URL

## Platform

<!-- TODO(bạn): Railway hoặc Render -->
Railway

## Cách deploy (Railway)

```bash
cd 06-lab-complete
railway login
railway init                      # tạo project mới
railway add --database redis      # tạo Redis trong cùng project
railway up                        # build bằng Dockerfile (railway.toml: builder = "DOCKERFILE")
railway domain                    # tạo public URL
```

Trên dashboard, service agent → **Variables**:

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | chuỗi bí mật tự chọn (không ghi vào repo) |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` (biến tham chiếu tới service Redis) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `PORT` | do Railway tự cấp — CMD của Dockerfile lắng nghe `${PORT:-8000}` |

Healthcheck của Railway gọi `/health` (`railway.toml`).

*(Dùng Render thay thế: New → Blueprint → chọn repo, Render đọc `06-lab-complete/render.yaml`, tạo web service + Key Value (Redis) và nối `REDIS_URL` tự động; chỉ cần nhập `AGENT_API_KEY` vì khai báo `sync: false`.)*

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên nền tảng. Mỗi lệnh chỉ in mã HTTP nên chụp ảnh không lộ key.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả:

```
<!-- TODO(bạn): dán 4 dòng mã HTTP thực tế: 200 / 200 / 401 / 200 -->
```

Rate limit (gọi 12 lần, từ lần thứ 11 phải là 429):

```bash
for i in $(seq 1 12); do curl -sS -o /dev/null -w "$i: %{http_code}\n" -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'; done
```

Kiểm tra bằng script chấm:

```bash
cd 06-lab-complete && python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set

- `PORT` (platform cấp)
- `REDIS_URL`
- `AGENT_API_KEY`
- `ENVIRONMENT`
- `RATE_LIMIT_PER_MINUTE`
- `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

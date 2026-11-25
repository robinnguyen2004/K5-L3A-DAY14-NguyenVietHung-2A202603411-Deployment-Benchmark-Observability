# Day 14 Lab — Mission Answers

> Môi trường chạy: Windows 11, Docker Desktop (WSL2 backend), Python 3.13 trong venv. Các bài cần tín hiệu SIGTERM chạy trong container Linux.
> Mọi output dưới đây được copy từ lệnh đã chạy; token/key đã được che.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hardcode secret: `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL` chứa `admin:password123` | 17–18 | Push lên GitHub là lộ key/mật khẩu; đổi key phải sửa code và deploy lại |
| 2 | Log ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log của platform, ai đọc log cũng thấy (đã thấy thật trong log khi chạy, xem 1.2) |
| 3 | `print()` thay vì structured logging, log cả nội dung câu hỏi/câu trả lời | 33, 38 | Không parse/lọc được trong log aggregator, có thể lộ dữ liệu người dùng |
| 4 | Không có `/health` (và `/ready`) | — | Platform không biết app chết để restart, LB không biết khi nào route traffic (gọi thử trả **404**) |
| 5 | Port cố định `port=8000`, không đọc `PORT` | 52 | Railway/Render/Cloud Run cấp `PORT` động → app không nhận traffic |
| 6 | Bind `host="localhost"` | 51 | Trong container chỉ nhận kết nối từ chính container, bên ngoài không gọi được |
| 7 | `reload=True` và `DEBUG = True` cố định | 21, 53 | Reloader tốn tài nguyên, tạo process con; debug mode trong production |
| 8 | Config cứng (`MAX_TOKENS = 500`, `DEBUG`) | 21–22 | Muốn đổi giữa dev/staging/prod phải sửa code (vi phạm 12-Factor "Config") |
| 9 | Không xử lý shutdown (không lifespan / SIGTERM) | — | Deploy/scale-in cắt ngang request đang chạy |

### Exercise 1.2: Chạy bản develop

```
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Log server — secret bị in ra:

```
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
```

→ Chạy được, nhưng không production-ready: không health check, lộ secret trong log, chỉ nghe trên localhost.

Bản production (`cp .env.example .env && python app.py`):

```
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":5.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:40:10.592129+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}
```

### Exercise 1.3: So sánh develop vs production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`OPENAI_API_KEY`, `DEBUG`, `MAX_TOKENS`) | `config.py` đọc env (`os.getenv`), có `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production | Cùng một image chạy được ở mọi môi trường; secret không nằm trong git; đổi config không cần build lại |
| Secrets | Ghi thẳng trong code, còn in ra log | Lấy từ env, log chỉ ghi độ dài câu hỏi | Tránh lộ key qua git/log |
| Health check | Không có (404) | `/health` (liveness, có uptime) + `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform tự restart khi chết; LB không route vào instance chưa sẵn sàng |
| Logging | `print()` text tự do | JSON (`{"time","level","msg"}` + `json.dumps` event) | Log aggregator (Loki, Datadog) parse/lọc/đếm được theo field |
| Shutdown | Đột ngột (không lifespan) | `lifespan` + handler SIGTERM; uvicorn chờ request đang chạy | Rolling deploy / scale-in không làm rớt request |
| Host/Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Chạy được trong container và trên PaaS cấp port động |
| Reload/Debug | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Không chạy reloader trong production |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép gọi từ trình duyệt |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — bản Python đầy đủ (Debian + build tools), rất nặng (image cuối 1.67 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo từng layer. Copy riêng `requirements.txt` rồi `pip install` trước khi `COPY` code thì khi chỉ sửa code, layer cài dependencies vẫn dùng cache → build lại chỉ vài giây. Nếu `COPY . .` trước, mỗi lần sửa 1 dòng code là cache bị vô hiệu và phải `pip install` lại từ đầu.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là chương trình chính luôn được chạy; `CMD` là lệnh/tham số mặc định, bị ghi đè khi `docker run image <lệnh khác>`. Dùng chung thì `CMD` trở thành tham số cho `ENTRYPOINT`. Cả hai nên dùng exec form (`["python","app.py"]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy bản develop

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --rm --name p2dev -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker?"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":5.1,"container":true}
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (builder):** `python:3.11-slim` + cài `gcc`, `libpq-dev`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này có compiler/build tools, **không** được deploy.
- **Stage 2 (runtime):** `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (packages đã cài) + `main.py` + `utils/`; có `HEALTHCHECK`, `CMD uvicorn ... --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, header, apt cache, pip cache, và dùng base `slim` (~120 MB) thay vì `python:3.11` full (~1 GB).

```
$ docker images my-agent
REPOSITORY   TAG        SIZE
my-agent     advanced   240MB
my-agent     develop    1.67GB
$ docker image inspect my-agent:develop my-agent:advanced --format "{{index .RepoTags 0}} {{.Size}}"
my-agent:develop 1667775969
my-agent:advanced 239815291
```

- Develop: **1667.8 MB** (1 667 775 969 bytes)
- Production: **239.8 MB** (239 815 291 bytes)
- Chênh lệch: production nhỏ hơn **85.6%** (= 1 − 239.8 / 1667.8), tức nhỏ hơn ~7 lần.

### Exercise 2.4: Docker Compose stack

Sơ đồ (`02-docker/production/docker-compose.yml`):

```
            Client (curl)
                 │  :80
         ┌───────▼────────┐
         │  nginx:alpine  │  reverse proxy + rate limit 10r/s, security headers
         └───────┬────────┘
                 │ http://agent:8000   (network "internal", không expose port agent)
         ┌───────▼────────┐
         │     agent      │  FastAPI, build từ Dockerfile multi-stage (target runtime)
         └───┬────────┬───┘
   redis://redis:6379  http://qdrant:6333
     ┌───────▼──┐   ┌──▼────────────┐
     │  redis   │   │    qdrant     │   (cả hai có healthcheck; agent depends_on
     │ 7-alpine │   │ vector DB RAG │    condition: service_healthy)
     └──────────┘   └───────────────┘
```

Service giao tiếp qua DNS nội bộ của Docker (tên service) trên bridge network `internal`; chỉ Nginx publish cổng 80/443 ra ngoài.

```
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 8 seconds (healthy)    8000/tcp
nginx     nginx:alpine            Up 8 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 19 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 19 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":7.7,"version":"2.0.0","timestamp":"2026-11-25T08:42:51.275960"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Header `Server: nginx` và các security header chứng tỏ request đi qua Nginx rồi mới tới agent.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

Theo CHECKPOINTS (CP6), lớp K5 deploy thẳng agent Part 6 trong `06-lab-complete/` thay vì app mẫu `03-cloud-deployment/`.

- Nền tảng chính: **Render** (Exercise 3.2), Blueprint `06-lab-complete/render.yaml` (Blueprint Path đặt thủ công vì file không ở gốc repo)
- URL: **https://day14-agent-6q0z.onrender.com**
- Redis: Render Key Value `day14-redis`, `REDIS_URL` của agent nối qua `fromService` (connection string nội bộ); `/ready` trả `{"status":"ready","redis":"ok"}`
- `AGENT_API_KEY` khai báo `sync: false`, nhập trên dashboard lúc tạo Blueprint, không ghi trong code/repo
- Kết quả 4 lệnh tự kiểm: `/health` → 200, `/ready` → 200, `/ask` không key → 401, `/ask` có key → 200; vượt 10 request/phút → 429 (`Retry-After: 51`)
- `check_production_ready.py --public-url https://day14-agent-6q0z.onrender.com` → `✅ Public URL: GET .../health → 200`
- Nền tảng còn lại (Railway): không deploy, thay bằng phần so sánh `railway.toml` / `render.yaml` bên dưới
- Chi tiết lệnh và ảnh: [DEPLOYMENT.md](DEPLOYMENT.md), `screenshots/dashboard.png`, `running.png`, `test.png`

### So sánh `railway.toml` và `render.yaml` (06-lab-complete)

| Khía cạnh | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng / phạm vi | TOML, cấu hình **1 service** (build + deploy) | YAML Blueprint, khai báo **nhiều service** (web + Key Value/Redis) trong một file (Infrastructure as Code) |
| Build | `builder = "DOCKERFILE"` | `runtime: docker`, `dockerfilePath`, thêm `rootDir: 06-lab-complete` vì Render build từ repo GitHub |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `MaxRetries = 3` | Render tự restart, không cấu hình trong file |
| Secret | Không khai báo trong file; đặt bằng `railway variables set` / dashboard | Khai báo key nhưng không có giá trị: `sync: false` (nhập tay) hoặc `generateValue: true` (Render tự sinh) |
| Redis | Thêm plugin Redis trên dashboard, gán `REDIS_URL` bằng biến tham chiếu | Khai báo service `keyvalue` ngay trong Blueprint và nối bằng `fromService ... property: connectionString` |
| PORT | Railway inject `PORT`, CMD của Dockerfile dùng `${PORT:-8000}` | Render inject `PORT` tương tự |

Vì sao khác: Railway thiên về CLI (`railway up` đẩy thư mục local) nên file chỉ mô tả cách build/chạy 1 service, phần hạ tầng còn lại cấu hình trên dashboard. Render dùng mô hình Blueprint đọc từ GitHub, nên toàn bộ hạ tầng (web + Redis + biến môi trường) nằm trong file, secret được đánh dấu để nhập ngoài git.

### Exercise 3.3: Pipeline CI/CD Cloud Run (`cloudbuild.yaml` + `service.yaml`)

1. **test:** Cloud Build chạy container `python:3.11-slim`, cài requirements + pytest và chạy `pytest tests/`; fail thì dừng pipeline.
2. **build:** `docker build` image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache (`waitFor: [test]`).
3. **push:** đẩy mọi tag lên Container Registry (`waitFor: [build]`).
4. **deploy:** `gcloud run deploy ai-agent` với image theo `COMMIT_SHA` (truy vết/rollback được), region `asia-southeast1`, `min-instances=1` (tránh cold start), `max-instances=10`, 512Mi/1 CPU, timeout 60s, env `ENVIRONMENT=production`, secret `OPENAI_API_KEY` lấy từ Secret Manager.
5. `service.yaml` mô tả cùng service dạng Knative khai báo: autoscale 1–10 instance theo `containerConcurrency: 80`, `livenessProbe /health`, `startupProbe /ready`, secret `AGENT_API_KEY` qua `secretKeyRef`.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop`, chạy `AGENT_API_KEY=secret-key-123 python app.py`)

- **Check ở đâu:** dependency `verify_api_key()` dùng `APIKeyHeader(name="X-API-Key")`, gắn vào `/ask` bằng `Depends(verify_api_key)`.
- **Sai key:** thiếu header → **401**; có header nhưng sai → **403** (bản mẫu phân biệt hai trường hợp; agent Part 6 của tôi trả 401 cho cả hai theo đúng hợp đồng).
- **Rotate key:** key đọc từ env `AGENT_API_KEY` → đổi biến môi trường trên platform rồi restart/redeploy, không sửa code. Muốn không downtime thì hỗ trợ tạm 2 key (cũ + mới) trong thời gian chuyển đổi.

```
# Không có key
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Có key đúng
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

JWT flow: `POST /auth/token` kiểm tra username/password → `create_token()` ký HS256 payload `{sub, role, iat, exp(+60 phút)}` bằng `JWT_SECRET` → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm tra chữ ký + hạn, lấy `username`/`role` mà không cần tra database.

```
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN_ĐÃ_CHE>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN_ĐÃ_CHE>"}

# Không có token
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Có token
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** Sliding Window Log — mỗi user một `deque` timestamp, bỏ timestamp cũ hơn 60s, đếm số còn lại.
- **Giới hạn:** user thường `10 req/phút` (`rate_limiter_user`), admin `100 req/phút` (`rate_limiter_admin`).
- **Bypass cho admin:** `/ask` chọn limiter theo `role` trong JWT — token role `admin` (tài khoản `teacher`) dùng limiter 100 req/phút. Muốn bỏ hẳn thì bỏ qua `limiter.check()` khi `role == "admin"`.
- Hạn chế của bản mẫu: state nằm trong RAM của process → mỗi instance/worker đếm riêng, restart là mất. Agent Part 6 của tôi lưu trong Redis.

```
# (request "Explain JWT" ở trên đã tính 1 lượt)
$ for i in $(seq 1 12); do curl -s -o /dev/null -w "Request $i: HTTP %{http_code}\n" -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\":\"Test $i\"}"; done
Request 1: HTTP 200
Request 2: HTTP 200
Request 3: HTTP 200
Request 4: HTTP 200
Request 5: HTTP 200
Request 6: HTTP 200
Request 7: HTTP 200
Request 8: HTTP 200
Request 9: HTTP 200
Request 10: HTTP 429
Request 11: HTTP 429
Request 12: HTTP 429

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Test 13"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 58
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}

$ curl -s http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":280,"cost_usd":0.000174,"budget_usd":1.0,"budget_remaining_usd":0.999826,"budget_used_pct":0.0}
```

10 request thành công (1 + 9) rồi bị chặn 429 kèm `Retry-After`. Nhận xét nhỏ: field `usage.budget_remaining_usd` trong response `/ask` của bản mẫu thực ra trả `total_cost_usd` (đã dùng), không phải số còn lại.

### Exercise 4.4: Cost guard — cách tôi làm (agent Part 6, `06-lab-complete/app/cost_guard.py`)

- **Đo chi phí:** sau mỗi lần gọi LLM, ước lượng token (~4 ký tự/token) của câu hỏi và câu trả lời, `cost = in/1000 × $0.00015 + out/1000 × $0.0006` (giá gpt-4o-mini).
- **Lưu ở Redis, không ở RAM:** `INCRBYFLOAT cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM` trong một pipeline, kèm `EXPIRE` (2 ngày / 32 ngày) → tự "reset" theo ngày/tháng vì key mới, mọi worker/instance dùng chung tổng.
- **Chặn trước khi gọi LLM:** `check_budget()` đọc 2 key bằng `MGET`; nếu tổng ngày ≥ `DAILY_BUDGET_USD` hoặc tổng tháng ≥ `MONTHLY_BUDGET_USD` → `HTTP 402 Payment Required`. Budget đọc từ biến môi trường.
- **Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ *tốc độ* (chống spam/DoS theo từng key), cost guard bảo vệ *tiền* (tổng chi). 10 req/phút × nhiều key × prompt dài vẫn có thể đốt hết ngân sách; ngược lại cost guard không ngăn được một client làm nghẽn service trong vài giây.
- Script chấm xác nhận: với `DAILY_BUDGET_USD=0.000001` agent trả **402 ở request thứ 1** sau khi request đầu tiên đã ghi chi phí (xem output ở Part 6).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

- `/health` (liveness): process còn sống thì trả 200, kèm uptime và mức dùng RAM (psutil). Fail → platform **restart** container.
- `/ready` (readiness): trả 503 khi app đang khởi động/đang tắt (`_is_ready=False`), 200 khi sẵn sàng, kèm số request đang xử lý. Fail → LB **ngừng gửi traffic** nhưng không restart.
- Khác biệt: liveness không nên phụ thuộc dịch vụ ngoài (Redis chết mà restart agent cũng không giải quyết được gì), readiness thì nên kiểm tra phụ thuộc. Agent Part 6 của tôi làm đúng như vậy: `/health` luôn 200, `/ready` 503 khi ping Redis lỗi.

```
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:45:57.869548+00:00","checks":{"memory":{"status":"ok","used_percent":10.6}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

### Exercise 5.2: Graceful shutdown

Bản develop đếm `_in_flight_requests` bằng middleware; khi SIGTERM, uvicorn ngừng nhận kết nối mới, lifespan shutdown đặt `_is_ready=False` và chờ tối đa 30s cho request đang chạy xong rồi mới thoát. Test chạy trong container Linux (Windows không gửi được SIGTERM), `docker stop` gửi SIGTERM ngay khi request đang xử lý:

```
$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &  ;  docker stop p5dev
Kết quả request đang chạy:
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}  -> HTTP 200
docker stop mất 3.5s, exit code container: 0

$ docker logs p5dev
INFO:     172.17.0.1:49096 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
2026-11-25 08:46:01,111 INFO 🔄 Graceful shutdown initiated...
2026-11-25 08:46:01,111 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
2026-11-25 08:46:01,111 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Request đang chạy vẫn trả 200, container thoát với exit code 0 (không phải 137/SIGKILL).

### Exercise 5.3: Stateless design

`05-scaling-reliability/production/app.py` lưu session/history ở Redis (`session:<id>`, `SETEX` TTL 3600s) thay vì dict trong RAM. Lý do: khi scale ra nhiều instance sau load balancer, request kế tiếp của cùng user có thể rơi vào instance khác; nếu history nằm trong RAM của instance A thì instance B không thấy → mất ngữ cảnh. Instance chết/restart cũng mất hết state. Redis là state dùng chung nên instance nào cũng phục vụ được, và có thể thêm/bớt/khởi động lại instance tùy ý.

### Exercise 5.4: Load balancing (3 instance + Nginx, cổng 8080, `POST /chat`)

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 11 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 10 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 21 seconds (healthy)   6379/tcp

# 10 request, in ra instance phục vụ (served_by)
instance-07c00d
instance-436065
instance-bae5f5
instance-07c00d
instance-436065
instance-bae5f5
instance-07c00d
instance-436065
instance-bae5f5
instance-07c00d
```

Nginx (`upstream agent:8000`, Docker DNS trả về 3 IP) phân phối round-robin đều cho 3 instance.

### Exercise 5.5: Test stateless

```
$ python test_stateless.py
Session ID: de600c8b-d50b-4c9b-b028-b06e8f51f449

Request 1: [instance-436065]   Q: What is Docker?
Request 2: [instance-bae5f5]   Q: Why do we need containers?
Request 3: [instance-07c00d]   Q: What is Kubernetes?
Request 4: [instance-436065]   Q: How does load balancing work?
Request 5: [instance-bae5f5]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-07c00d', 'instance-436065', 'instance-bae5f5'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

Giải thích: 5 câu trong cùng 1 session được 3 instance khác nhau xử lý, nhưng history đọc lại đủ 10 message (5 user + 5 assistant) → state không nằm trong instance nào mà nằm ở Redis.

Thử thêm (script không tự làm): tắt hẳn 1 instance rồi hỏi tiếp cùng session:

```
$ docker stop k5-day14-scaling-agent-1
Request 6 -> instance-436065 | storage: redis
Request 7 -> instance-07c00d | storage: redis
Request 8 -> instance-436065 | storage: redis
$ curl -s http://localhost:8080/chat/<session_id>/history  → Total messages: 16
```

Mất 1 instance, Nginx chuyển traffic sang 2 instance còn lại, session vẫn tiếp tục (10 → 16 message).

---

## Part 6: Final Project — output `check_production_ready.py`

Chạy đầy đủ (có Docker, không `--skip-docker`) trong môi trường Linux: container `python:3.11-slim` + Docker CLI, dùng Docker daemon của máy qua socket (`--network host`), vì Python trên Windows không gửi được SIGTERM (README K5 mục 2).

```
$ python check_production_ready.py
...
✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 16s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Docker: container chạy được, GET /health → 200
...
✅ 7. Rate limiting
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ 8. Cost guard
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1
...
✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

### Thiết kế chính của agent Part 6

| Tiêu chí | Cách làm (file) |
|---|---|
| Config | `app/config.py`: dataclass, mọi field `default_factory=os.getenv(...)`; `AGENT_API_KEY` mặc định rỗng → chưa cấu hình thì mọi `/ask` bị 401 (fail-closed) |
| Auth | `app/auth.py`: `APIKeyHeader("X-API-Key")`, so sánh bằng `secrets.compare_digest` (chống timing attack); thiếu/sai → 401 |
| Redis | `app/redis_client.py`: `redis.from_url` lười kết nối (app khởi động được khi chưa có Redis), timeout 1–2s để `/ready` trả 503 nhanh |
| Rate limit | `app/rate_limiter.py`: sliding window bằng sorted set (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `EXPIRE`), key = hash SHA-256 của API key (không lưu key gốc), vượt → 429 + `Retry-After` tính từ request cũ nhất trong cửa sổ |
| Cost guard | `app/cost_guard.py`: `INCRBYFLOAT` theo ngày & tháng, chặn 402 trước khi gọi LLM (xem 4.4) |
| Health/Ready | `/health` luôn 200; `/ready` 503 khi ping Redis lỗi hoặc đang shutdown |
| Logging | `JsonFormatter` tự viết, mỗi dòng 1 JSON (`ts, lvl, logger, event` + field); middleware log mọi request (`method, path, status, ms`) |
| Lỗi | validation → 422 gọn (không trả input); `RedisError` → 503; lỗi khác → 500 `"Internal server error"`, không lộ stack trace |
| Shutdown | `lifespan`: không tự đăng ký signal handler (để không đè handler của uvicorn); uvicorn nhận SIGTERM, ngừng nhận kết nối, chờ request đang chạy rồi chạy phần sau `yield` |
| Docker | 2 stage (`builder` cài vào `/opt/venv`, `runtime` chỉ copy venv + `app/` + `utils/`), user `app` non-root, HEALTHCHECK bằng Python (slim không có curl), `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers 2"]` → uvicorn là PID 1; image 273 MB |
| Compose | `agent` (build) + `redis:7-alpine` (healthcheck, AOF volume), `REDIS_URL=redis://redis:6379/0`, `depends_on: condition: service_healthy`, `env_file .env required: false` |

---

## AI log

> Theo RULES.md mục 1: ghi lại mọi lần dùng AI cho code Part 6 và cho câu trả lời.

Công cụ: Claude Code (Claude Opus) chạy trong VS Code, làm theo từng checkpoint của đề.

| # | Phần | Hỏi / giao việc gì | Nhận được gì | Tôi tự sửa và kiểm tra thế nào |
|---|---|---|---|---|
| 1 | Toàn bài | Đọc README/RULES/CHECKPOINTS/RUBRIC, tóm tắt yêu cầu và lộ trình | Bảng checkpoint, thứ tự TODO Part 6, các lưu ý K5 | Đối chiếu lại với RUBRIC (Part 6 = 60/120) và lưu ý K5 trong README |
| 2 | Part 6 code | Viết các TODO trong `06-lab-complete/` (config, auth, redis, rate limit, cost guard, main, Dockerfile, compose, deploy config) theo hợp đồng của script chấm | Code như trong repo; AI đọc `check_production_ready.py` để biết cách chấm (`--workers 2` → state bắt buộc ở Redis; container phải chạy được khi không có Redis; slim không có curl) | Chạy `check_production_ready.py`: Windows 11/12 (graceful ⚠️ vì Windows không có SIGTERM), sau đó chạy đầy đủ trong Linux → **PASS 12/12**. Bỏ một exception handler thừa do middleware đã xử lý |
| 3 | Part 1, 2, 4, 5 | Chạy các ví dụ, ghi output curl, đo kích thước image | Output trong file này | Phát hiện và sửa: tiến trình reloader của bản develop giữ cổng 8000 khiến curl gọi nhầm app; dọn rồi chạy lại. Git Bash gửi body tiếng Việt sai encoding → gửi body từ file UTF-8. Số MB lấy từ `docker image inspect` |
| 4 | Part 5.2 | Test graceful shutdown | Chạy app trong container Linux, `docker stop` khi request đang chạy | Request vẫn 200, exit code 0 (lần đầu container chưa kịp cài xong deps → tách bước cài thành image riêng rồi chạy lại) |
| 5 | Part 7.1–7.3 | Thêm metric `agent_question_length_chars`; sửa `KNOWLEDGE_BASE` cho 2 câu sai; viết job CI | Histogram + 2 entry KB (`hpa/autoscal/kubernetes`, `jwt/api key`), `.github/workflows/eval.yml` | Kiểm tra trong `golden_dataset.jsonl` không câu nào khác chứa các keyword mới (tránh regression do top_k=1); eval cuối 23/23, `regressions: []`. Không sửa `golden_dataset.jsonl` |
| 6 | Part 7.4–7.6 | Bật stack, Locust headless, tìm trace, chụp ảnh, phá hệ thống | Lỗi Dockerfile production của đề (HOME của user `agent` là `/app` nên Python không thấy `/home/agent/.local` → `No module named uvicorn`), sửa bằng `ENV PYTHONUSERBASE`; script theo dõi trạng thái alert mỗi 5s; ảnh chụp bằng Chrome headless trong network của stack | Thời gian firing đọc từ log watcher; trace_id đối chiếu với `docker compose logs agent`; số trong BENCHMARK_REPORT lấy từ JSON/CSV bằng script |
| 7 | Sự cố | Ổ D: (chứa repo) bị ngắt giữa chừng | Dừng, kiểm tra lại toàn bộ file khi ổ quay lại | Mọi file còn nguyên; khởi động lại Docker, chạy lại stack cho thí nghiệm D, E |

Lưu ý tự kiểm: mọi con số trong bài và trong `BENCHMARK_REPORT.md` đều lấy từ lệnh đã chạy / file JSON-CSV đã nộp, không có số ước lượng.

# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON (`reports/`), CSV của Locust (`benchmark-results/`), Prometheus API và screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Việt Hùng — 2A202603411
**Ngày chạy:** 25/11/2026
**Môi trường:** Laptop Intel Core i7-12700H (20 luồng), RAM 15.7 GB, Windows 11 + Docker Desktop 29.9.3 (WSL2 backend). Bước 1 chạy agent bằng Python 3.13 (venv) trên Windows; Bước 2 chạy Docker Compose (mỗi agent giới hạn 0.5 CPU / 256 MB).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–250 ms mỗi call, cộng retrieval ~20 ms → request bình thường ~200 ms; 500 ms cho ~2× khoảng đệm khi tải tăng mà người dùng chat vẫn thấy "tức thì". Đây cũng là ngưỡng mặc định của `load_test.py`. Alert đặt lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn |
| Error rate `/ask` | < 2 % | Upstream LLM mock lỗi ~1% (`MOCK_ERROR_RATE=0.01`) là mức "bình thường" không kiểm soát được; 2% chừa error budget cho lỗi của chính mình. Alert ở 5% trong 1 phút |
| Accuracy trên golden dataset | ≥ 85 % (CI), mục tiêu 100 % | Job CI (`.github/workflows/eval.yml`) chặn merge nếu < 85% hoặc có bất kỳ câu nào regression so với baseline đã commit. Bản v2 sau khi sửa KB đạt 100% (23/23) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.0 | 202.3 | 238.6 | 1721.6 | 1.33% | ✅ PASS |
| 10 | 31.96 | 207.7 | 494.2 | 1723.2 | 1.00% | ✅ PASS |
| 50 | 92.25 | 225.2 | 583.0 | 1754.6 | 0.33% | ❌ FAIL (p95) |
| 100 | 111.83 | 285.5 | 630.4 | 2004.2 | 1.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS tăng gần tuyến tính từ 1 → 10 (4.0 → 31.96, ×8 với ×10 concurrency) vì agent dùng `async` và LLM chỉ là `await asyncio.sleep`, nên nhiều request chờ song song được. Từ 10 → 50 chỉ tăng ×2.9, từ 50 → 100 chỉ thêm ×1.2: agent chạy **1 process uvicorn** (1 event loop, 1 core) phải tự serialize JSON, middleware metrics, log cho mọi request, và client `load_test.py` cũng chạy trên cùng máy, nên CPU thành nút thắt. Khi đó request phải xếp hàng trong event loop → p50 tăng từ 202 lên 285 ms, p95 vượt SLO từ concurrency 50. Muốn đẩy RPS tiếp phải scale ngang (nhiều worker/instance), không phải tăng concurrency.

### 2.2 Tail latency (agent v2, `--requests 300 --concurrency 20`)

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (khởi động lại v2 với từng giá trị `MOCK_SLOW_RATE`).

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 227.6 | 487.0 | 523.6 |
| 0.03 (mặc định) | 268.8 | 518.6 | 1723.4 |
| 0.1 | 385.3 | 1716.8 | 1735.6 |

**Nhận xét:** Từ 0 → 0.03, avg chỉ tăng 18% (227.6 → 268.8 ms) nhưng p99 tăng **3.3 lần** (523.6 → 1723.4 ms): 3% request chậm thêm 1.5 s bị "pha loãng" trong trung bình nhưng chiếm trọn phần đuôi từ p97 trở lên. Lên 0.1 thì 10% request chậm vượt qua mốc 5% → **p95 nhảy từ 518.6 lên 1716.8 ms**, trong khi avg vẫn chỉ 385 ms trông "ổn". Vì vậy p95/p99 là chỉ số nhạy nhất. SLO không nên đặt theo average vì average che đi đúng nhóm người dùng có trải nghiệm tệ: avg 269 ms nghe tốt, nhưng cứ 100 người thì vài người chờ gần 2 giây.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 56.7 | 109.1 | 116.0 |
| Tổng cost (USD) | 0.000398 | 0.000762 | 0.000810 |
| Cost / câu đúng (USD) | 0.00039795 | 0.00003627 | 0.00003524 |
| Quality gate | FAIL (ngưỡng 80%) | PASS (ngưỡng 80%, 0 regression so với v1) | PASS (ngưỡng 100%, 0 regression so với v2) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry KB kích hoạt bởi `["hpa", "autoscal", "kubernetes"]`: "Kubernetes HPA ... dựa trên CPU, memory hoặc custom metrics (vd RPS, độ dài hàng đợi)..." |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry KB kích hoạt bởi `["jwt", "api key"]`: "API key ... không tự hết hạn ... JWT là token có chữ ký số ... thời điểm hết hạn (exp)..." |

Trước khi thêm, tôi kiểm tra trong `golden_dataset.jsonl` không có câu nào khác chứa `hpa`, `kubernetes`, `jwt`, `api key`, vì retrieval chỉ lấy top-1 tài liệu theo số keyword trùng: keyword quá rộng có thể "giành" tài liệu của câu khác và gây regression. Eval cuối: `regressions: []`, 2 câu được cải thiện. Phần sửa cũng được chép sang `production/utils/mock_llm.py` để stack Docker dùng cùng knowledge base.

Ghi chú: lần eval cuối có p95 = 1695.9 ms chỉ vì 1/23 request trúng "slow" ngẫu nhiên. Đây đúng là cảnh báo của README: 23 câu không đủ mẫu để kết luận về latency.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
v2 thêm bước retrieval nên prompt dài gần gấp đôi (56.7 → 109.1 token/câu), tổng cost tăng 1.9× (0.000398 → 0.000762 USD) và p95 tăng ~32 ms (197.5 → 229.8 ms trong output eval). Đổi lại accuracy từ 4.35% lên 91.3%, nên **cost / câu đúng giảm ~11 lần** (0.00039795 → 0.00003627 USD). So "cost / câu" thì v1 rẻ hơn, nhưng v1 gần như luôn trả lời sai nên số tiền đó là lãng phí; "cost / câu đúng" mới phản ánh giá của giá trị thật mà người dùng nhận. Sau khi sửa KB, cost tăng nhẹ (+6%) nhưng cost / câu đúng còn giảm tiếp xuống 0.00003524 USD.

**Quality gate trong CI:** `run_eval.py` trả exit code 1 khi accuracy < `--min-accuracy` hoặc có câu regression so với `--baseline`. Chạy thử v1 với `--baseline reports/eval_v2.json` → "Câu bị regression: 20", `Quality gate ... ❌ FAIL`, **exit=1**. Job `.github/workflows/eval.yml` chạy lệnh này cho mọi pull request; step trả exit code ≠ 0 làm job fail, và khi bật branch protection "Require status checks to pass" thì PR không merge được.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png) (Locust 30 user, 2 instance; trước đó là 2 lượt benchmark scale). Thêm ảnh lúc đang làm thí nghiệm A–C: [`screenshots/grafana-dashboard-experiments.png`](screenshots/grafana-dashboard-experiments.png)
- [x] Một trace chậm trong Jaeger — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`) — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png) (`AgentHighErrorRate` + `AgentHighLatencyP95` cùng firing)

Trả lời câu hỏi Exercise 7.4 (đọc trên dashboard lúc 30 user, 2 instance — ảnh `grafana-dashboard.png`):

1. **p95 và avg:** stat "Latency p95" trên ảnh là **288.21 ms**. Đường avg nằm sát p50 (~200 ms) trên biểu đồ; Locust đo cùng loại tải cho avg /ask 233.5 ms (`scale_1_stats.csv`). Trong khi đó đường p99 nằm ở ~1.7–1.8 s. p95 và avg gần nhau vì >95% request là request bình thường; khoảng cách lớn nằm giữa avg và p99, đó là tail latency do ~3% request chậm của LLM. Chỉ nhìn avg sẽ không thấy nhóm người dùng phải chờ gần 2 giây.
2. **Requests/s theo instance:** Nginx chia gần đều. Prometheus đo `increase(http_requests_total{route="/ask"}[3m])` sau lượt scale 3: 2403 và 2405 request cho 2 instance mới, instance cũ cao hơn (4113) chỉ vì nó đã chạy từ lượt scale 1 trước đó. Panel "Requests/s theo instance" cho thấy các đường chồng lên nhau.
3. **Input tokens/s > output tokens/s:** input gồm system prompt + tài liệu retrieval + câu hỏi, còn output chỉ là câu trả lời ngắn. Đo được với v2: input ≈ 1426.6 token/s, output ≈ 755.9 token/s. Ở mock, mỗi request v2 có 81 token input và 46 token output.
4. **`curl http://localhost:8080/metrics`:** trả **404 Not Found** của Nginx. `nginx.conf` chặn `/metrics` từ bên ngoài, vì metrics lộ thông tin nội bộ (tên model, cost, số request) và không nên public. Prometheus scrape thẳng từng container agent trong network nội bộ `obs_net` qua DNS service discovery, không đi qua Nginx.

Alert rules được unit test: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: Locust chạy nền 30 user suốt thí nghiệm; một script poll `GET /api/v1/alerts` mỗi 5 giây và ghi lại mọi lần đổi trạng thái kèm giờ. "Thời gian → firing" tính từ lúc áp dụng thay đổi (`docker compose up -d` với `.env` mới, hoặc `docker pause`). A, B, C chạy nối tiếp (B giữ nguyên lỗi của A để có ảnh 2 alert cùng firing); D, E chạy sau khi stack được khởi động lại.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (pending 16:06:22, firing 16:07:22) | **79 s** (đổi lúc 16:06:03) | Error rate (stat đỏ), "Requests/s theo status code" (503 tăng), "LLM calls theo kết quả" (error) |
| B | `MOCK_SLOW_RATE=0.3` (giữ error 0.2) | `AgentHighLatencyP95` (pending 16:08:28, firing 16:10:28) | **148 s** (đổi lúc 16:08:00) | "Latency /ask — p50/p95/p99": p95 và p99 vọt lên ~1.7 s, avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (pending 16:11:23, firing 16:13:24) — cost đo được **$16.30/giờ** | **142 s** (đổi lúc 16:11:02) | "Cost burn rate (USD/giờ)", "LLM cost (1h)" |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (activeAt 16:35:02, firing 16:35:32) | **38 s** (pause lúc 16:34:54) | "Instances up" 2 → 1. Error rate của agent vẫn xanh (1.18%), trong khi Nginx trả **28 lỗi 504** (request treo tới `proxy_read_timeout 10s`) và Locust thấy max latency 10005 ms |
| E | `AGENT_VERSION=v1` | **Không có** (quan sát 16:36:24 → 16:40:38, `/api/v1/alerts` trả `[]`) | — | "Retrieval hit ratio": `agent_retrieval_total` ngừng tăng (trước đó 17.7 hit/s); "Tokens/s" giảm còn ~một nửa (input 1426.6 → 691.5, output 755.9 → 376.5 token/s); `agent_info` của cả 2 instance là `version="v1"`. Trong khi đó p95 = 198 ms, error rate = 1.04% → dashboard toàn xanh dù accuracy thực tế rớt từ 100% xuống ~4% (eval v1) |

Các quan sát phụ:
- **Thời gian firing ≈ thời gian cửa sổ `rate()` cộng `for`.** A cần ~19 s để `rate(...[1m])` có đủ mẫu vượt 5%, cộng `for: 1m` thành 79 s. B cần đủ mẫu chậm để p95 > 1 s, cộng `for: 2m`. D nhanh nhất vì `up == 0` đúng ngay sau 1 lần scrape lỗi, chỉ cần `for: 30s`.
- **`LLMCostBurnRateHigh` đã firing ngay ở tải nền** (16:03:37, model small, sau 2 lượt Locust 100 user). Với 30 user, v2 cũng đốt khoảng $1.36/giờ, sát ngưỡng $2/giờ. Ngưỡng này nên tính theo traffic dự kiến chứ không đặt cố định.
- Trong B, `LLMCostBurnRateHigh` chuyển về inactive: request chậm hơn → mỗi user Locust gửi ít request hơn → tốc độ đốt tiền giảm. Đây là ví dụ cho thấy metric cost phụ thuộc vào cả latency.
- Mỗi lần `docker compose up -d` tạo lại agent, `AgentInstanceDown` của IP cũ chỉ lên `pending` vài giây rồi về `inactive`: container bị xoá khỏi DNS nên Prometheus coi là target biến mất, không phải "down". Đúng như README giải thích vì sao bài D dùng `pause` chứ không dùng `stop`.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng chỉ trả lời "có nhanh, có lỗi HTTP không", không trả lời "có đúng không". v1 trả 200 rất nhanh và còn rẻ hơn, nên mọi panel đều xanh. Cách phát hiện:
1. **Chặn trước khi deploy:** eval golden dataset trong CI (`eval.yml`) với `--baseline`. v1 bị 20 câu regression → exit 1 → không merge/deploy được.
2. **Giám sát chất lượng khi chạy:** chạy eval định kỳ trên production (synthetic check bằng golden dataset mỗi N phút, alert khi accuracy giảm); theo dõi metric proxy cho chất lượng như retrieval hit ratio (rơi về 0 khi chuyển v1), độ dài câu trả lời, tỉ lệ câu trả lời "chung chung"; alert khi `agent_info{version}` đổi ngoài quy trình release.
3. **Tín hiệu từ người dùng và LLM-as-judge:** nút 👍/👎, tỉ lệ hỏi lại; chấm mẫu ngẫu nhiên ~1% hội thoại bằng LLM-as-judge rồi đẩy điểm thành metric để vẽ và alert như metric hạ tầng.

### 4.3 Debug bằng trace

Chọn trace chậm nhất tìm được (Jaeger, `POST /ask`, duration ≥ 1 s, 458 trace thoả điều kiện trong 20 phút):

- `trace_id`: `50c4ac2bd0651417f99d243095d6e4c6`
- Tổng thời gian: **1743.0 ms** (`POST /ask`, HTTP 200)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1716.8 ms, 98.5%**). Các span còn lại: `agent.run` 1739.2 ms (span cha), `agent.retrieve_context` 22.3 ms (1.3%). Attributes: `gen_ai.request.model = mock-llm-small`, `gen_ai.usage.input_tokens = 81`, `gen_ai.usage.output_tokens = 46`. Kết luận: chậm do upstream LLM (request rơi vào nhóm "slow"), không phải do code agent hay retrieval.
- Dòng log tương ứng (`docker compose logs agent | grep 50c4ac2bd0651417f99d243095d6e4c6`):

```json
{"ts": "2026-11-25T08:59:11.164352+00:00", "level": "INFO", "service": "observable-agent", "instance": "305fc7e6bbf3", "event": "llm_call", "trace_id": "50c4ac2bd0651417f99d243095d6e4c6", "span_id": "15d270f17e298423", "request_id": "c43e5a294578", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1675.8}
{"ts": "2026-11-25T08:59:11.166424+00:00", "level": "INFO", "service": "observable-agent", "instance": "305fc7e6bbf3", "event": "http_request", "trace_id": "50c4ac2bd0651417f99d243095d6e4c6", "span_id": "15d270f17e298423", "request_id": "c43e5a294578", "method": "POST", "route": "/ask", "status": 200, "ms": 1742.0}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`): `trace_id` `fd66d53079913ae7eb76af153fe75019`, `POST /ask` → **503**, 116.2 ms. Span `chat mock-llm-small` (92.2 ms) có `error.type = upstream_unavailable`, status error và event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`). Log cùng trace:

```json
{"ts": "2026-11-25T09:05:17.608106+00:00", "level": "INFO", "service": "observable-agent", "instance": "305fc7e6bbf3", "event": "llm_error", "trace_id": "fd66d53079913ae7eb76af153fe75019", "span_id": "195f8fa2a1166241", "request_id": "af003b9fa39c", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T09:05:17.608319+00:00", "level": "INFO", "service": "observable-agent", "instance": "305fc7e6bbf3", "event": "http_request", "trace_id": "fd66d53079913ae7eb76af153fe75019", "span_id": "195f8fa2a1166241", "request_id": "af003b9fa39c", "method": "POST", "route": "/ask", "status": 503, "ms": 115.8}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

Nguồn: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv` (dòng `/ask`; dòng `Aggregated` gồm cả `/health` ghi trong ngoặc).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.79 (Aggregated 65.95) | 190 | 230 | 1700 | 52 / 7120 (0.73%) |
| 3 | 60.23 (Aggregated 66.16) | 190 | 220 | 1700 | 65 / 7208 (0.90%) |

**Giải thích kết quả:** Scale 1 → 3 instance gần như **không đổi** gì: RPS +0.7%, p95 230 → 220 ms (chênh trong mức nhiễu), p99 vẫn 1700 ms. Có hai lý do:
1. **Tải bị giới hạn bởi chính kịch bản Locust (closed-loop).** 100 user, mỗi user chờ `between(0.5, 2)` s sau mỗi request, request mất ~0.2 s → tối đa khoảng 100 / (1.25 + 0.2) ≈ 69 req/s. Đo được 66 req/s, nghĩa là bên tạo tải đã chạm trần, 1 instance vẫn phục vụ kịp. Thêm instance không làm người dùng gửi nhanh hơn.
2. **Latency bị chi phối bởi LLM, không phải CPU của agent.** Panel "LLM latency p95" ~199 ms và trace cho thấy span `chat` chiếm ~98% thời gian. Mock LLM là `await asyncio.sleep`, nên 1 instance async xử lý song song được nhiều request đang chờ. p99 = 1700 ms là các request "slow" của LLM; scale ngang không sửa được tail latency của upstream.

Nút thắt nằm ở **upstream LLM** (và ở bên tạo tải trong thí nghiệm này). Scale ngang chỉ có ích khi agent bão hoà CPU/kết nối (thấy ở mục 2.1 khi concurrency ≥ 50 trên 1 process). Muốn giảm p95/p99 thật phải xử lý phía LLM: timeout + retry/hedging cho request chậm, cache câu trả lời, streaming để cải thiện thời gian tới token đầu tiên, hoặc chọn model/provider nhanh hơn.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Percentile quan trọng hơn trung bình.** Cùng lượt đo, avg 269 ms nhưng p99 1723 ms; tăng `MOCK_SLOW_RATE` lên 0.1 làm p95 tăng 3.3 lần trong khi avg chỉ tăng 43%. SLO và alert phải đặt theo p95/p99.
  2. **Metric hạ tầng không thấy lỗi chất lượng, và metric của một service không thấy lỗi ở tầng trước nó.** Thí nghiệm E (v1) không alert nào kêu dù accuracy rớt từ 100% xuống 4%; thí nghiệm D có 28 lỗi 504 ở Nginx nhưng error rate của agent vẫn xanh. Cần eval/quality gate và giám sát ở LB / synthetic check bổ sung.
  3. **Ba trụ cột phải nối với nhau bằng `trace_id`.** Dashboard báo p99 cao → Jaeger chỉ ra span `chat` chiếm 98.5% → grep `trace_id` trong log JSON thấy `llm_ms = 1675.8`. Nhờ vậy xác định được trong vài phút rằng nguyên nhân là upstream, không phải code. Cũng nhờ benchmark mà biết scale ngang không giúp gì cho tail latency.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Alert **SLO burn rate** nhiều cửa sổ (vd 5m + 1h theo error budget 30 ngày) thay cho ngưỡng tức thời, để giảm báo động giả và không bỏ sót suy giảm chậm.
  - Metric/alert ở **tầng Nginx/LB** (tỉ lệ 5xx/504, upstream response time) và **synthetic probe** từ bên ngoài gọi `/ask` thật mỗi phút.
  - **Chất lượng:** eval định kỳ trên production + alert khi accuracy giảm; retrieval hit ratio; điểm LLM-as-judge trên mẫu hội thoại; tỉ lệ 👎.
  - **LLM-specific:** time-to-first-token, tỉ lệ 429/timeout theo provider, alert ngân sách theo ngày dựa trên cost thật (ngưỡng tính theo traffic dự kiến), tokens/request p95 để bắt prompt phình to.
  - **Saturation:** in-flight requests / event-loop lag, CPU/memory theo container, độ trễ và lỗi kết nối Redis.

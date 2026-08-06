# Agentic FinOps Governance for Cloud Infrastructure and AI Services

A production-style capstone demo that governs cloud spend across **two domains from one agent**:

- **Infrastructure** — virtual machine CPU, memory, disk and network utilization from CoreStack-derived Azure telemetry plus AWS/GCP telemetry generated from open trace patterns.
- **AI services** — managed LLM inference cost, tokens, latency and answer quality. Amazon Bedrock is the primary test service; Azure OpenAI and Vertex AI demonstrate a provider-neutral design.

## Main Outcome

You ask one plain-English question. The agent decides which domain owns the answer, and returns
decisions in a single shape no matter where they came from:

| Question | Routed to | Typical decision |
|---|---|---|
| Which VMs can be shut down during low peak hours? | Infrastructure | `SCHEDULE_SHUTDOWN` |
| Which VMs need scale down / scale up? | Infrastructure | `SCALE_DOWN` / `SCALE_UP` |
| Which applications are degraded? | Infrastructure | `DB_INVESTIGATION` |
| Which workloads can use a smaller model? | AI services | `SWITCH_TO_SMALLER_MODEL` |
| Where are we wasting input or output tokens? | AI services | `ENABLE_PROMPT_CACHING` |
| Where can we save the most money across the estate? | **Both** | one ranked list |

Every decision carries structured evidence, estimated savings, confidence, business impact, risk and an
approval-gated Lambda payload. A question that spans both domains returns one list ranked by savings,
with the per-analyst reasoning shown separately.

## Quick Start

```bash
git clone https://github.com/pranyth/proactive-finops-agentic.git
cd proactive-finops-agentic

python3 -m venv venv
source venv/bin/activate       # Windows PowerShell: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_demo.py
```

Open `http://127.0.0.1:8000`. API documentation is at `http://127.0.0.1:8000/docs`.

The first run creates the normalized synthetic AI dataset automatically. Rebuild it with:

```bash
python run_demo.py --regenerate
```

## LLM Configuration

The complete demo works without a cloud key using the evidence-policy fallback. To generate the final explanation with a real LLM, copy `.env.example` to `.env`, load it into your shell, and configure one provider:

```bash
export FINOPS_LLM_PROVIDER=openai
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4o-mini
python run_demo.py
```

Anthropic and local Ollama adapters are also supported. Secrets must never be committed.

## Architecture

```text
VM utilization telemetry ─┐
                          ├─> FastAPI gateway -> persisted event bus -> coordinator
Bedrock / AI usage metrics┘                                                  │
                                                                             v
                                          ┌──────────── domain router ───────────┐
                                          │                                      │
                             infrastructure analyst                    AI service analyst
                        (CPU / memory / disk / network,            (tokens, model tier,
                         cost, incidents, policy)                   quality, caching)
                                          │                                      │
                                          └─────> normalized decision <──────────┘
                                                          │
                                       optional LLM explanation -> evidence-backed
                                       recommendation -> approval-gated Lambda payload
```

Both analysts emit the same `Decision` contract (`agents/unified.py`), which is why one console can
render a VM shutdown and a model switch as the same kind of card. AWS Lambda is the execution
mechanism for an approved shutdown, resize, model, cache or tier change.

## Console

Four views, all driven by the same API:

- **Ask** — free-text question, auto-detected domain (or pin one), estate KPIs, ranked decisions, evidence drawer.
- **Infrastructure** — utilization meters for all four signals, CPU-band distribution, cost by provider and environment, per-machine CPU/memory/disk/network history.
- **AI services** — spend by provider, cost by deployment, token/quality/latency evidence table.
- **Activity** — event bus, coordinator audit trail, Lambda payloads proposed.

## Production Vision

See [docs/FINAL_PROJECT_VISION.md](docs/FINAL_PROJECT_VISION.md) for the target LangGraph/LangChain architecture, autonomous agent responsibilities, production AWS Lambda workflow, migration boundary and resume-ready project description.

## Data

CoreStack did not supply AI-service billing data. The project therefore generates a reproducible 30-day AI workload using:

- existing CoreStack-derived enterprise context;
- Microsoft Azure public LLM inference trace patterns;
- Amazon Bedrock CloudWatch metric definitions;
- explicit synthetic scenarios generated with seed `42`.

The data is stored in normalized SQLite tables rather than one flat CSV. See [docs/AI_FINOPS_DATASET.md](docs/AI_FINOPS_DATASET.md) for provenance and paper-use rules.

## Important API Endpoints

- `POST /api/query` — natural-language question across both domains. Optional `domain` of `auto` (default), `infrastructure`, `ai_services` or `all`
- `GET /api/overview` — merged estate KPIs: infrastructure and AI services side by side
- `GET /api/infra/summary` — fleet utilization, CPU bands, provider/environment cost, top spenders
- `GET /api/infra/resource/{id}` — hourly CPU, memory, disk and network for one machine
- `GET /api/ai-finops/summary` — cost, token, provider and recommendation summary
- `GET /api/suggestions` — the example questions the console offers
- `POST /api/demo-run` — push one telemetry event and one AI usage event through the coordinator
- `GET /api/events` — persisted event stream
- `GET /api/architecture` — runtime architecture

## Tests

```bash
python -m unittest discover -s tests
```

Covers domain routing, the shared decision contract across both analysts, the merged overview
totals, fleet reads and the event paths.

## Current Safety Boundary

Lambda execution is simulated and logged. The demo never changes a real cloud service. Production changes require credentials, policy controls, approval workflow and provider-specific adapters.

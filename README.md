# AI Senate

Deterministic AI consensus specification coordinator, powered by [opencode](https://opencode.ai).

Multiple "perspective" agents (architect, DBA, coder, etc.) each backed by a different LLM, review a technical specification in parallel rounds, build consensus, and a writer agent rewrites the spec.

## Architecture

```
┌──────────────────┐    HTTP     ┌──────────────────┐    HTTP     ┌──────────────────┐
│  React + Vite    │  /api/*     │  FastAPI         │  /session   │  opencode server │
│  SPA (frontend/) │ ──────────▶ │  (app/main.py)   │ ──────────▶ │  :4096           │
│  Tailwind + shadcn             │  orchestrator    │             │  + cliproxy      │
└──────────────────┘             └──────────────────┘             │  + opencode-go   │
                                                                 └──────────────────┘
```

- **Single entry point**: `opencode` REST API (`http://127.0.0.1:4096`).
- **One agent adapter**: `app/agent_adapters/opencode.py` (replaces old cli/api/mock).
- **JSON API** only: FastAPI serves `/api/*` endpoints, SPA is the only HTML.
- **Pydantic v2**.

## Quick start

### 1. Backend

```bash
cd /opt/ai-lab/ai-senate
pip install -r requirements.txt
OPENCODE_PASSWORD=your_opencode_web_password \
  uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Set the opencode-go provider key (one-time, via opencode API):
```bash
curl -u opencode:$PASSWORD -X PUT http://127.0.0.1:4096/auth/opencode-go \
  -H "Content-Type: application/json" \
  -d '{"type": "api", "key": "sk-..."}'
```

### 2. Frontend (dev)

```bash
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173 (proxies /api → :8765)
```

### 3. Frontend (prod)

```bash
cd frontend
npm run build  # output → app/web/static/
```

FastAPI will then serve the SPA on the same port as the API.

## Perspectives

Configured in `app/config/agents.yaml` and `~/.opencode/agents/`:

| Key | Provider | Model | Role |
|---|---|---|---|
| `glm51` | opencode-go | glm-5.1 | Critical — edge cases |
| `qwen37max` | opencode-go | qwen3.7-max | Code Reviewer |
| `minimax` | opencode-go | minimax-m3 | Architect |
| `deepseekv4pro` | opencode-go | deepseek-v4-pro | DBA |
| `writer` | cliproxy | claude-opus-4-6-thinking | Spec writer |

## Tests

```bash
OPENCODE_PASSWORD=... python3 -m pytest tests/ -v -p no:cacheprovider
```

## API

See `app/web/api.py` for full list. Key endpoints:

- `GET /api/health` — opencode reachability
- `GET /api/config` — perspectives + juries
- `GET /api/runs` — list runs
- `POST /api/runs` — start a new council run
- `GET /api/runs/{id}` — run detail (status, agents, round_log)
- `GET /api/runs/{id}/findings` — findings grouped by category
- `GET /api/runs/{id}/consensus` — consensus result
- `GET /api/runs/{id}/updated-spec` — generated spec text
- `GET /api/runs/{id}/changes` — changes summary
- `POST /api/runs/{id}/accept` — accept the spec as `data/spec.md`

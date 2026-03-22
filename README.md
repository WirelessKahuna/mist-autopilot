# Mist Autopilot
### Self-Driving Network Org Health Review

Mist Autopilot automatically detects problems, diagnoses root cause, and recommends corrective actions across every site in a Mist-managed organization — reducing the need for manual network operations.

---

## Quick Start

### 1. Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A Mist API token with read access to your org

### 2. Configure
```bash
cp .env.example .env
```
Edit `.env` and fill in:
```
MIST_API_TOKEN=your_token_here
MIST_ORG_ID=your_org_id_here
```

### 3. Run
```bash
docker compose up
```

Open your browser to **http://localhost:3000**

That's it.

---

## Architecture

```
mist-autopilot/
├── backend/          Python + FastAPI
│   ├── main.py       API entrypoint
│   ├── mist_client.py  Shared async Mist API client
│   ├── models/       Pydantic data models
│   ├── modules/      8 analysis modules (+ base class)
│   └── routers/      REST API routes
└── frontend/         React + Vite + Tailwind
    └── src/
        ├── api/      Axios API client
        ├── components/  Reusable UI components
        └── pages/    Dashboard view
```

### How Modules Work

Every module inherits from `BaseModule` and implements one method:

```python
async def analyze(self, org_id, sites, client) -> ModuleOutput:
    ...
```

All 8 modules run in parallel on every dashboard refresh. Adding a new module requires:
1. Create `backend/modules/my_module.py` inheriting `BaseModule`
2. Register it in `backend/modules/__init__.py`

It appears in the dashboard automatically.

---

## Modules

| Module | Status | Autonomy Level |
|--------|--------|----------------|
| 📡 RoamGuard — Roaming Health | In development | L1 + L2 |
| 📊 SLE Sentinel | In development | L1 + L2 + L3 |
| 🔍 Config Drift Detective | In development | L1 + L2 + L3 |
| 📶 RF Fingerprint Analyzer | In development | L1 + L2 |
| 🔐 SecureScope | In development | L1 + L2 |
| 📈 Client Experience Trends | In development | L1 + L2 |
| 🔄 AP Lifecycle Monitor | In development | L1 + L3 |
| 🌐 WAN & Uplink Sentinel | In development | L1 + L2 |

---

## API Reference

Interactive API docs available at **http://localhost:8000/docs** when running.

| Endpoint | Description |
|----------|-------------|
| `GET /api/org/summary` | Run all modules, return full org health |
| `GET /api/org/sites` | List all sites |
| `GET /api/modules/` | List module registry |
| `GET /api/modules/{id}` | Run a single module |
| `GET /api/health` | Health check |

---

## Security

- API token is stored only in `.env` — never committed to Git
- `.env` is in `.gitignore`
- All Mist API calls are server-side — the token never reaches the browser
- No data is persisted to disk — all results are in-memory

---

## Development

To work on a module without Docker:

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env  # fill in your values
uvicorn main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

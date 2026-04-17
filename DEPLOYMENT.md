# Deployment Guide — Elfie Lab Analyzer

Target stack:

- **Frontend** → Vercel (Vite static build)
- **Backend** → Render (Docker web service)
- **Database** → Render managed Postgres 16
- **Auth** → Supabase (existing project)

---

## 1. Prerequisites

- GitHub repo with this code pushed
- Render account (connect GitHub)
- Vercel account (connect GitHub)
- Supabase project with:
  - JWT secret (Dashboard → Settings → API → JWT Secret)
  - Anon public key
  - Project URL
- Qwen (DashScope) API key with access to `qwen-turbo` and `qwen3-vl-flash`

---

## 2. Secrets — Rotate Before Deploy

Any key already committed to `.env` must be rotated:

- `ELFIE_QWEN_API_KEY` → generate new in DashScope console, revoke old
- `ELFIE_SUPABASE_JWT_SECRET` → rotate in Supabase if suspected leak
- Supabase anon keys → rotate if exposed

Verify `.env` is git-ignored:

```bash
git check-ignore .env   # should print `.env`
git ls-files | grep -E '^\.env$'   # should print nothing
```

---

## 3. Backend → Render

### Option A: Blueprint (recommended)

1. Push repo to GitHub.
2. Render Dashboard → **New** → **Blueprint** → select this repo.
3. Render parses `render.yaml` at root → creates:
   - Postgres `elfie-labs-db`
   - Web service `elfie-labs-backend` (Docker, root `backend/`)
4. Fill in the `sync: false` secrets in dashboard:
   - `ELFIE_QWEN_API_KEY`
   - `ELFIE_SUPABASE_JWT_SECRET`
   - `ELFIE_SUPABASE_URL`
5. After Vercel deploy (Step 4) update `ELFIE_CORS_ORIGINS` to real Vercel domain, e.g. `["https://elfie-labs.vercel.app"]`.
6. Apply → Render builds Docker image, runs Alembic migrations on boot, starts uvicorn.

### Option B: Manual

- New Postgres → copy connection string.
- New Web Service → Docker → `backend/Dockerfile` → root dir `backend`.
- Set env vars from `render.yaml` manually.
- Health check path: `/api/health/ready`.

### Migrations

Run automatically by `backend/scripts/docker_start.sh` → `alembic upgrade head` before uvicorn starts. Render URL scheme (`postgresql://`) is rewritten to `postgresql+asyncpg://` at boot.

### Artifact storage (PHI)

`artifacts/` currently writes to local disk inside container — **ephemeral on Render**. Before production:

- Mount Render persistent disk (paid), OR
- Swap to S3/GCS via `artifact_store_path` abstraction, OR
- Use Supabase Storage bucket

---

## 4. Frontend → Vercel

1. Vercel Dashboard → **Add New → Project** → import repo.
2. **Root Directory**: `frontend`.
3. Framework preset: **Vite**.
4. Build command: `npm run build` (auto-detected).
5. Output directory: `dist`.
6. Env vars (Project Settings → Environment Variables):
   - `VITE_API_URL` = `https://elfie-labs-backend.onrender.com` (Render backend URL)
   - `VITE_SUPABASE_URL` = your Supabase project URL
   - `VITE_SUPABASE_ANON_KEY` = Supabase anon public key
7. Deploy → note the production URL, e.g. `https://elfie-labs.vercel.app`.
8. Go back to Render → update `ELFIE_CORS_ORIGINS` with that URL → redeploy backend.

SPA routing handled by `frontend/vercel.json` rewrites.

---

## 5. Post-Deploy Verification

```bash
# Backend health
curl https://elfie-labs-backend.onrender.com/api/health
# → {"status":"ok"}

curl https://elfie-labs-backend.onrender.com/api/health/ready
# → 200

# CORS preflight from Vercel origin
curl -X OPTIONS https://elfie-labs-backend.onrender.com/api/upload \
  -H "Origin: https://elfie-labs.vercel.app" \
  -H "Access-Control-Request-Method: POST" -i | head -20
# → 200, Access-Control-Allow-Origin echoed
```

Upload a PDF from the Vercel site → confirm:

- Job appears in `/api/jobs/{id}`
- Patient artifact returns ≥ expected row count
- No `ReadTimeout` errors in Render logs

---

## 6. Production Hardening Checklist

- [ ] `ELFIE_DEV_AUTH_BYPASS=false` in Render env
- [ ] `ELFIE_DEBUG=false` and `ELFIE_ALLOW_DEBUG_ARTIFACTS=false`
- [ ] `ELFIE_CORS_ORIGINS` is exact Vercel domain, not `["*"]`
- [ ] Rotate Qwen + Supabase secrets
- [ ] Confirm no `.env`, `clin.json`, `pdfs/`, `artifacts/` tracked in git
- [ ] Migrate artifact storage off ephemeral disk (S3 / Supabase Storage)
- [ ] Upgrade Render plan to `standard` if VLM latency spikes
- [ ] Upgrade Postgres plan beyond `basic-256mb` for production traffic
- [ ] Enable Render auto-deploy only on `main` branch
- [ ] Add rate limit / upload quota middleware (currently none)
- [ ] Review frontend bundle size (current 514KB → split with dynamic imports)
- [ ] Verify migration chain linear: `20260410_0001 → 0002 → 0003 → 20260415_0004` is head

---

## 7. Cost Estimate (baseline)

| Service | Plan | Cost/mo |
|---------|------|---------|
| Vercel Hobby | Free | $0 |
| Render Postgres basic-256mb | Free (90d) → $7 | $0-7 |
| Render Starter web | 512MB | $7 |
| Qwen API | Pay-per-token | Variable |
| Supabase | Free tier | $0 |

Expected: **$7–15/mo** at low traffic. Scale backend to `standard` ($25) when VLM concurrency demands it.

---

## 8. Rollback

```bash
# Render: Dashboard → Service → Events → click prior deploy → Rollback
# Vercel: Dashboard → Project → Deployments → "..." → Promote to Production
# DB: Render Postgres → Backups → restore point-in-time (paid plans)
```

---

## 9. Local Dev Still Works

```bash
docker compose up                # Postgres + backend on :8000
cd frontend && npm install && npm run dev   # Vite on :5173, proxies /api
```

`.env` values for local dev remain unchanged.

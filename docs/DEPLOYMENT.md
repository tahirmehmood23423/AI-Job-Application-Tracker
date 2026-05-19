# Deployment Guide

This document walks you through deploying the Resume Parser API to production. Render is the recommended platform for a first deployment: free tier eligible, zero-config Docker, and 30-second deploys. Railway and Fly.io work identically.

## Pre-deployment checklist

Before deploying, make sure you can run the service locally end-to-end:

```bash
cd resume-parser-api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
uvicorn app.main:app --reload
```

Visit <http://localhost:8000/docs> and try a parse with one of your own resumes. If that works, you're ready to deploy.

Also run the tests:

```bash
pytest -v
```

## Option 1: Deploy to Render (recommended)

### Step 1 — Push your code to GitHub

```bash
git init
git add .
git commit -m "Initial commit: resume parser API"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/resume-parser-api.git
git push -u origin main
```

### Step 2 — Create a Render Web Service

1. Sign up at [render.com](https://render.com) (free, no credit card required).
2. Click **New +** → **Web Service**.
3. Connect your GitHub account and select the `resume-parser-api` repo.
4. Fill in the form:
   - **Name**: `resume-parser-api`
   - **Region**: closest to your users
   - **Branch**: `main`
   - **Runtime**: `Docker`
   - **Instance Type**: `Free` (good for testing; upgrade to Starter $7/month for production — the free tier sleeps after 15 min idle)

### Step 3 — Add environment variables

In the Render dashboard, under **Environment**, add these:

| Key | Value |
|-----|-------|
| `ANTHROPIC_API_KEY` | your real key |
| `LLM_PROVIDER` | `anthropic` |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` |
| `APP_ENV` | `production` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGINS` | your frontend URL (or `*` while testing) |

Render injects `PORT` automatically; you don't set that.

### Step 4 — Deploy

Click **Create Web Service**. Render builds the Docker image (3–5 minutes the first time) and starts it. When the status shows "Live", visit:

- `https://YOUR-SERVICE.onrender.com/health` → should return `{"status":"ok"}`
- `https://YOUR-SERVICE.onrender.com/docs` → interactive API docs

### Step 5 — Test a real parse

```bash
curl -X POST https://YOUR-SERVICE.onrender.com/api/v1/parse \
  -F "file=@/path/to/your/resume.pdf"
```

If you get back structured JSON — congratulations, Module 1 is live.

## Option 2: Deploy to Railway

Almost identical workflow. Railway auto-detects the Dockerfile.

1. Sign up at [railway.app](https://railway.app).
2. **New Project** → **Deploy from GitHub repo** → select your repo.
3. In the service's **Variables** tab, add the same env vars as the Render section.
4. Railway generates a public domain under **Settings → Networking → Generate Domain**.

## Option 3: Deploy to Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch --no-deploy   # answer prompts; it auto-detects Dockerfile
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set LLM_PROVIDER=anthropic
fly deploy
```

## Custom domain (optional but recommended for the portfolio)

If you own a domain (e.g. `tahir.dev`), add a subdomain like `api.tahir.dev`:

1. In Render → **Settings → Custom Domains** → add `api.tahir.dev`.
2. In your DNS provider, add a CNAME record:  
   `api.tahir.dev` → `YOUR-SERVICE.onrender.com`
3. Wait 5–10 minutes for SSL to provision automatically.

A custom domain makes the service look professional on your LinkedIn post and resume.

## Monitoring & cost

- **Render free tier**: 750 hours/month, sleeps after 15 min idle. Fine for testing.
- **Render Starter ($7/mo)**: no sleep, 512 MB RAM, recommended once you have real users.
- **LLM costs**: Claude Haiku 4.5 costs roughly $0.001–$0.003 per resume parsed. At 1,000 parses/month that's $1–$3. Set a usage cap in the Anthropic console as a safety net.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails on Render | Missing requirements pin | Re-check `requirements.txt` |
| 502 on first request | Free tier was asleep | Wait 30s for cold start, retry |
| `LLMConfigurationError: ANTHROPIC_API_KEY is not set` | Env var not added | Add it in Render dashboard, redeploy |
| Slow responses (10s+) | LLM provider latency | Try `claude-haiku-4-5-20251001` (faster), or switch to `openai`/`gpt-4o-mini` |
| `422 — File could not be parsed` on a real PDF | Scanned/image PDF with no text layer | Out of scope for Module 1; OCR is a future enhancement |

## Once it's deployed

Open `docs/LINKEDIN_POST.md` for a suggested LinkedIn post to announce your new service. This is your first build-in-public moment for the AI Job Application Tracker.

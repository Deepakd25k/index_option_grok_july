# Index Premarket Dashboard

Sheet-style HTML dashboard for Indian index pre-market bias.

**Repo:** https://github.com/Deepakd25k/index_option_grok_july

```
Upstox (GIFT + indices)  ─┐
Yahoo (fallback + Europe) ─┼→ FastAPI → HTML UI
NSE FII OI CSV (free)     ─┤
MrChartist FII/DII cash   ─┘
```

## Features

- Column-wise live sheet (India / US / Asia / Europe / Gap / Cash / FII OI)
- **GIFT Nifty auto** via Upstox (no manual paste)
- **FII Index Futures OI** from NSE official CSV — contracts + **%**
- **1-week FII OI trend** + next-day match accuracy (Bias & Flow)
- Significance guide tab
- Free sources only (no Google Sheet bill)

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# optional: UPSTOX_ACCESS_TOKEN=your_token

./run.sh
# → http://127.0.0.1:8765
```

## Vercel deploy

1. Import this GitHub repo in [vercel.com](https://vercel.com) → **Add New Project**
2. Framework: Other / Python (auto)
3. Root directory: `.` (repo root)
4. **Environment Variables** (Project → Settings → Environment Variables):

| Name | Value | Required |
|------|--------|----------|
| `UPSTOX_ACCESS_TOKEN` | Your Upstox API access token | **Yes for GIFT Nifty** |
| `DAILY_RETENTION_DAYS` | `90` | Optional |
| `WEEKLY_RETENTION_WEEKS` | `104` | Optional |
| `GAP_SMALL_PCT` | `0.30` | Optional |
| `GAP_MEDIUM_PCT` | `0.70` | Optional |

5. Deploy → open the `*.vercel.app` URL
6. Click **↻ Refresh** once after deploy

### Where to put Upstox API key (Vercel)

```
Vercel Dashboard
  → your project (index_option_grok_july)
  → Settings
  → Environment Variables
  → Key:   UPSTOX_ACCESS_TOKEN
  → Value: <paste access token from Upstox app>
  → Environments: Production + Preview (both)
  → Save
  → Redeploy (Deployments → … → Redeploy)
```

**Upstox token kaise mile:**

1. https://account.upstox.com/developer/apps  
2. Create / open app → generate **Access Token**  
3. Copy token → Vercel env `UPSTOX_ACCESS_TOKEN`

Without token: Nifty/Bank/VIX/US/Asia/Europe/FII OI still work (Yahoo + NSE).  
**GIFT Nifty + gap** need Upstox token.

### Cron (auto refresh)

`vercel.json` schedules Mon–Fri:

| UTC | IST (approx) | Path |
|-----|--------------|------|
| 02:20 | 07:50 | `/api/refresh` pre-market |
| 13:45 | 19:15 | `/api/refresh` after OI publish |

Cron runs on **Production** only. Free Hobby: max 2 crons (we use 2).

## API

| Method | Path | Use |
|--------|------|-----|
| GET | `/` | HTML UI |
| GET/POST | `/api/refresh` | Pull all sources |
| GET | `/api/latest` | Last snapshot |
| GET | `/api/history` | Daily history |
| GET | `/api/docs` | Significance guide |
| GET | `/api/health` | Health + token flag |

## Note on Vercel storage

Serverless disk is ephemeral (`/tmp`). Each cold start may re-fetch.  
FII week trend always pulls last ~7 days from NSE live — no permanent store needed for that.

## License

Personal / research use. NSE & MrChartist data: non-commercial personal analysis.

# FestiFlip – WhatsApp Ticket Marketplace Automation

Automated WhatsApp-based ticket marketplace where buyers pay a deposit (7.5%, min €5/ticket) via Stripe, after which seller contact details are released. The remaining payment is handled directly between buyer and seller.

## Quick Start

### 1. Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
# Edit .env with your Stripe, WhatsApp, and OpenAI keys
```

### 2. Run Locally (SQLite)

```bash
# Start the server (auto-creates SQLite DB)
uvicorn app.main:app --reload
```

- **API docs**: http://localhost:8000/docs
- **Admin dashboard**: http://localhost:8000/admin/
- **Health check**: http://localhost:8000/health

### 3. Run Tests

```bash
python -m pytest tests/ -v
```

### 4. Migrate Excel Data

```bash
python scripts/migrate_excel.py --sell-file data/sell_offers.xlsx --buy-file data/buy_requests.xlsx --dry-run
# Remove --dry-run when ready to import
```

## Deploy to Railway

1. Push to GitHub
2. Connect repo in [Railway](https://railway.app)
3. Add a PostgreSQL plugin
4. Set environment variables in Railway dashboard:
   - `DATABASE_URL` (auto-set by Railway Postgres plugin)
   - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
   - `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`
   - `OPENAI_API_KEY`
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD`
5. Railway auto-deploys on push (runs migrations via `railway.toml`)

## Architecture

```
app/
├── main.py              # FastAPI entry point
├── config.py            # Environment settings
├── database.py          # Async SQLAlchemy
├── models/              # 9 ORM models (users, sell_offers, buy_requests, ...)
├── schemas/             # Pydantic request/response schemas
├── crud/                # Database CRUD operations
├── services/            # Business logic (deposit, Stripe, reservation, matching)
├── ai/                  # AI intent classification (rule-based + OpenAI)
├── routers/             # API endpoints (WhatsApp, Stripe, Admin, Health)
├── templates/           # Jinja2 admin dashboard HTML
├── static/              # CSS for admin dashboard
└── message_templates/   # Dutch WhatsApp message templates
```

## Business Flow

```
Buyer sends WhatsApp → AI classifies intent → Collects data
    → Matches with seller → Creates reservation (60 min timeout)
    → Generates Stripe deposit link → Buyer pays
    → Stripe webhook confirms → Seller contact released via WhatsApp
    → Buyer pays remaining to seller directly
```

## Commission Rules

| Ticket Price | 7.5% Amount | Minimum (€5) | Deposit |
|---|---|---|---|
| €60 × 1 | €4.50 | €5.00 | **€5.00** ✅ |
| €100 × 1 | €7.50 | €5.00 | **€7.50** |
| €60 × 2 | €9.00 | €10.00 | **€10.00** ✅ |
| €100 × 2 | €15.00 | €10.00 | **€15.00** |

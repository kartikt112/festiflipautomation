"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # ─── Database ───
    DATABASE_URL: str = "sqlite+aiosqlite:///./festiflip.db"

    # ─── Stripe ───
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:8000/payment/success"
    STRIPE_CANCEL_URL: str = "http://localhost:8000/payment/cancel"

    # ─── WhatsApp (Meta Cloud API) ───
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v21.0"
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""

    # ─── OpenAI (ChatGPT) ───
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ─── Admin ───
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"

    # ─── App ───
    APP_ENV: str = "development"
    APP_BASE_URL: str = "http://localhost:8000"
    RESERVATION_TIMEOUT_MINUTES: int = 60

    # ─── Broadcast ───
    # Comma-separated phone numbers that receive new listing notifications
    BROADCAST_NUMBERS: str = ""

    # ─── Escalation ───
    OWNER_PHONE: str = "+918010662763"  # Phone number (E.164) that receives escalation alerts

    # ─── Feature Flags ───
    USE_AI_ROUTER: bool = False

    # ─── Whapi (Unofficial API) ───
    WHAPI_TOKEN: Optional[str] = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

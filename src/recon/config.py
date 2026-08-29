import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {key}\n"
            f"Copy .env.example to .env and fill in all values."
        )
    return value

RAZORPAY_KEY_ID: str = _require("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET: str = _require("RAZORPAY_KEY_SECRET")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

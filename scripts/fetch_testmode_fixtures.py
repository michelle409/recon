from __future__ import annotations

"""Fetch Razorpay test-mode fixtures and save them to fixtures/testmode/."""

import json
import time
from pathlib import Path

import razorpay
from dotenv import load_dotenv
import os

load_dotenv()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "testmode"

ORDERS_TO_CREATE = [
    {"amount": 49900,  "currency": "INR", "notes": {"description": "order_1_499INR"}},
    {"amount": 150000, "currency": "INR", "notes": {"description": "order_2_1500INR"}},
    {"amount": 75000,  "currency": "INR", "notes": {"description": "order_3_750INR"}},
    {"amount": 200000, "currency": "INR", "notes": {"description": "order_4_2000INR"}},
    {"amount": 99900,  "currency": "INR", "notes": {"description": "order_5_999INR"}},
]


def load_credentials() -> tuple[str, str]:
    key_id = os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise EnvironmentError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env"
        )
    if not key_id.startswith("rzp_test_"):
        print(f"WARNING: key {key_id!r} does not look like a test-mode key.")
    return key_id, key_secret


def create_orders(client: razorpay.Client) -> list[dict]:
    orders = []
    for spec in ORDERS_TO_CREATE:
        order = client.order.create(spec)
        print(f"  Created order {order['id']}  amount={order['amount']}  status={order['status']}")
        orders.append(order)
        time.sleep(0.2)  # stay well inside rate limits
    return orders


def fetch_settlements(client: razorpay.Client) -> dict | None:
    try:
        response = client.settlement.all()
        print("  settlements.all() succeeded")
        return response
    except Exception as exc:
        print(f"  settlements.all() failed: {exc}")
        return None


def fetch_recon_report(client: razorpay.Client) -> dict | None:
    # Use the current month; the test-mode recon endpoint may return empty data.
    import datetime
    now = datetime.date.today()
    params = {"year": now.year, "month": now.month, "day": 1, "count": 500, "skip": 0}
    try:
        response = client.settlement.recon_report(params)
        print("  settlement.recon_report() succeeded")
        return response
    except AttributeError:
        # SDK version may not expose this method; fall back to raw request.
        try:
            response = client.utility.get_request(
                "/v1/settlements/recon/combined",
                params,
            )
            print("  recon via raw request succeeded")
            return response
        except Exception as exc2:
            print(f"  recon raw request also failed: {exc2}")
            return None
    except Exception as exc:
        print(f"  settlement.recon_report() failed: {exc}")
        return None


def save(filename: str, data: dict | list) -> Path:
    path = FIXTURES_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    key_id, key_secret = load_credentials()
    client = razorpay.Client(auth=(key_id, key_secret))

    saved: list[str] = []
    failed: list[str] = []

    # --- Orders ---
    print("\n[1/3] Creating orders...")
    try:
        orders = create_orders(client)
        path = save("orders.json", orders)
        print(f"  Saved {len(orders)} orders → {path}")
        saved.append("orders.json")
    except Exception as exc:
        print(f"  Order creation failed: {exc}")
        failed.append("orders.json")

    # --- Settlements ---
    print("\n[2/3] Fetching settlements...")
    settlements = fetch_settlements(client)
    if settlements is not None:
        path = save("settlements.json", settlements)
        print(f"  Saved → {path}")
        saved.append("settlements.json")
    else:
        failed.append("settlements.json")

    # --- Recon report ---
    print("\n[3/3] Fetching settlement recon report...")
    recon = fetch_recon_report(client)
    if recon is not None:
        path = save("recon_report.json", recon)
        print(f"  Saved → {path}")
        saved.append("recon_report.json")
    else:
        failed.append("recon_report.json")

    # --- Summary ---
    print("\n=== Summary ===")
    for name in saved:
        size = (FIXTURES_DIR / name).stat().st_size
        print(f"  SAVED   {name}  ({size} bytes)")
    for name in failed:
        print(f"  FAILED  {name}")


if __name__ == "__main__":
    main()

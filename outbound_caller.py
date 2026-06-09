"""
Outbound Caller — reads clients.json and triggers AI calls via Plivo.

Usage:
  python3 outbound_caller.py                  # call all clients
  python3 outbound_caller.py --id 1           # call specific client by id
  python3 outbound_caller.py --dry-run        # preview without making calls
"""

import os
import json
import argparse
import plivo
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

PLIVO_AUTH_ID    = os.getenv("PLIVO_AUTH_ID")
PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN")
PLIVO_NUMBER     = os.getenv("PLIVO_NUMBER")
SERVER_URL       = os.getenv("SERVER_URL")       # e.g. https://xyz.trycloudflare.com
CLIENTS_FILE     = os.getenv("CLIENTS_FILE", "clients.json")


def load_clients():
    with open(CLIENTS_FILE, "r") as f:
        return json.load(f)


def call_client(client: dict, dry_run: bool = False):
    """Initiate an outbound call to a single client."""
    name  = client.get("name", "Unknown")
    phone = client.get("phone")
    cid   = client.get("id")

    if not phone:
        logger.warning(f"[OUTBOUND] Skipping {name} — no phone number")
        return

    answer_url = f"{SERVER_URL}/outbound-call?client_id={cid}"
    logger.info(f"[OUTBOUND] {'[DRY RUN] ' if dry_run else ''}Calling {name} ({phone}) → {answer_url}")

    if dry_run:
        return

    try:
        client_sdk = plivo.RestClient(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN)
        response = client_sdk.calls.create(
            from_=PLIVO_NUMBER,
            to_=phone,
            answer_url=answer_url,
            answer_method="POST",
        )
        logger.info(f"[OUTBOUND] Call initiated — request_uuid: {response['request_uuid']}")
    except Exception as e:
        logger.error(f"[OUTBOUND] Failed to call {name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Outbound AI Caller")
    parser.add_argument("--id", help="Call a specific client by ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making calls")
    args = parser.parse_args()

    if not dry_run_check(args):
        return

    clients = load_clients()
    logger.info(f"[OUTBOUND] Loaded {len(clients)} clients from {CLIENTS_FILE}")

    if args.id:
        clients = [c for c in clients if str(c.get("id")) == str(args.id)]
        if not clients:
            logger.error(f"[OUTBOUND] No client found with id={args.id}")
            return

    for client in clients:
        call_client(client, dry_run=args.dry_run)


def dry_run_check(args):
    if args.dry_run:
        return True
    if not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN:
        logger.error("[OUTBOUND] PLIVO_AUTH_ID or PLIVO_AUTH_TOKEN missing from .env")
        return False
    if not PLIVO_NUMBER:
        logger.error("[OUTBOUND] PLIVO_NUMBER missing from .env (your Plivo phone number)")
        return False
    if not SERVER_URL:
        logger.error("[OUTBOUND] SERVER_URL missing from .env (e.g. https://xyz.trycloudflare.com)")
        return False
    return True


if __name__ == "__main__":
    main()

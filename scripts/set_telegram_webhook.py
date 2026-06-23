import os
import sys

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        sys.exit(1)

    base_url = os.getenv("WEBHOOK_BASE_URL")
    if not base_url:
        print("Error: WEBHOOK_BASE_URL not found in .env")
        sys.exit(1)

    webhook_url = f"{base_url.rstrip('/')}/api/v1/telegram/webhook"
    secret_token = os.getenv("WEBHOOK_SECRET_TOKEN")

    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    print(f"Setting webhook to: {webhook_url}")

    payload = {"url": webhook_url}
    if secret_token:
        payload["secret_token"] = secret_token
        print("Using WEBHOOK_SECRET_TOKEN for added security.")

    response = httpx.post(api_url, json=payload)

    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")


if __name__ == "__main__":
    main()

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

    # The domain should be the public URL where the webhook will be received.
    # In your case, it seems to be https://alliases.duckdns.org/BubbleBrain
    # Adjust this if needed!
    base_url = "https://alliases.duckdns.org/BubbleBrain"
    webhook_url = f"{base_url}/api/v1/telegram/webhook"

    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    print(f"Setting webhook to: {webhook_url}")

    response = httpx.post(api_url, json={"url": webhook_url})

    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")


if __name__ == "__main__":
    main()

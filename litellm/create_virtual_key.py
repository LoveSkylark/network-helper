import asyncio
import hashlib
import os

import httpx


BASE_URL = os.getenv("LITELLM_URL", "http://litellm:4000")
ALLOWED_MODELS = ["copilot-auto", "local-ollama"]


async def main() -> None:
    master_key = os.environ["LITELLM_MASTER_KEY"]
    virtual_key = os.environ["LITELLM_VIRTUAL_KEY"]
    headers = {"Authorization": f"Bearer {master_key}"}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        key_hash = hashlib.sha256(virtual_key.encode()).hexdigest()
        info_response = await client.get(
            "/key/info",
            headers=headers,
            params={"key": key_hash},
        )
        if info_response.is_success:
            info = info_response.json().get("info", {})
            if set(info.get("models") or []) != set(ALLOWED_MODELS):
                raise RuntimeError(
                    "The existing LibreChat virtual key has unexpected model permissions. "
                    "Remove it from LiteLLM and recreate it from the configured key."
                )
            print("LibreChat LiteLLM virtual key already exists with the expected model scope.")
            return
        if info_response.status_code != 404:
            raise RuntimeError(
                f"LiteLLM key lookup failed with HTTP {info_response.status_code}."
            )

        create_response = await client.post(
            "/key/generate",
            headers=headers,
            json={"key": virtual_key, "models": ALLOWED_MODELS},
        )
        if create_response.is_error:
            raise RuntimeError(
                f"LiteLLM virtual key creation failed with HTTP {create_response.status_code}."
            )
        print("Created the LibreChat LiteLLM virtual key.")


if __name__ == "__main__":
    asyncio.run(main())

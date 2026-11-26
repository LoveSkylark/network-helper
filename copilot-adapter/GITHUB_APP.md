# GitHub App setup for Copilot

1. In GitHub, open your organization's **Settings > Developer settings > GitHub Apps > New GitHub App**. Enter a name and homepage URL. Disable webhooks; this integration does not need a callback URL.
2. Under **Organization permissions**, set **Copilot Requests** to **Read-only**, then create the app. Copy its **App ID** into `COPILOT_APP_ID` in `.env`.
3. In the app settings, open **Credentials > Key pairs**, create a key, and securely save the downloaded PEM file. Base64-encode it without line breaks:

   ```sh
   base64 -w 0 /path/to/private-key.pem
   ```

   Copy the output into `COPILOT_APP_PRIVATE_KEY_B64` in `.env`. Keep both the PEM and its encoded value private.
4. Install the app on the organization that should be billed. Find the installation ID in the app installation's configuration URL or using [GitHub's installation API](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app); set `COPILOT_INSTALLATION_ID` in `.env`.
5. Ensure the organization permits Copilot requests from GitHub App installations. Set `COPILOT_AUTH_MODE=github_app` and generate a separate `COPILOT_ADAPTER_API_KEY` with `openssl rand -hex 32`.

The adapter mints and refreshes installation tokens automatically. Rebuild and restart the adapter after changing `.env`. See [GitHub's server-to-server authentication guide](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/server-to-server-tokens).

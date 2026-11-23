import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


PUBLIC_READ = {"principal_type": "user", "principal_id": "*", "permission": "read"}


def share_bundled_mcp_connections(request, token):
    desired = json.loads(os.environ["TOOL_SERVER_CONNECTIONS"])
    public_ids = {
        connection["info"]["id"]
        for connection in desired
        if connection["type"] == "mcp" and PUBLIC_READ in connection["config"].get("access_grants", [])
    }
    if not public_ids:
        return

    path = "configs/tool_servers"
    saved = request(path, token=token)
    updated = []
    for connection in saved["TOOL_SERVER_CONNECTIONS"]:
        server_id = (connection.get("info") or {}).get("id")
        if connection.get("type") != "mcp" or server_id not in public_ids:
            continue
        config = connection.get("config") or {}
        grants = config.get("access_grants") or []
        if PUBLIC_READ not in grants:
            connection["config"] = {**config, "access_grants": [*grants, PUBLIC_READ]}
            updated.append(server_id)
    if updated:
        request(path, saved, token=token)
        print(f"Shared MCP connections with signed-in users: {', '.join(updated)}.")


def bootstrap():
    email = os.environ.get("WEBUI_ADMIN_EMAIL")
    password = os.environ.get("WEBUI_ADMIN_PASSWORD")
    if not email or not password:
        raise ValueError("Set WEBUI_ADMIN_EMAIL and WEBUI_ADMIN_PASSWORD for the local administrator.")

    opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(path, data=None, token=None):
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(
            f"http://open-webui:8080/api/v1/{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        try:
            with opener.open(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            exc.close()
            raise ValueError(f"{req.get_method()} /api/v1/{path} returned HTTP {exc.code}.") from None

    session = request("auths/signin", {"email": email, "password": password})
    token = session.get("token")
    if not token or session.get("role") != "admin":
        raise ValueError("Local sign-in did not return an admin session; check password sign-in and MFA.")

    share_bundled_mcp_connections(request, token)

    functions = request("functions/list", token=token)
    if any(function["id"] == "copilot" for function in functions):
        print("Copilot Pipe already exists; leaving it unchanged.")
        return

    created = request(
        "functions/create",
        {"id": "copilot", "name": "Copilot", "content": "from copilot_pipe import Pipe", "meta": {}},
        token=token,
    )
    if not created or created.get("type") != "pipe":
        raise ValueError("Open WebUI did not register copilot as a Pipe.")
    if not created.get("is_active"):
        enabled = request("functions/id/copilot/toggle", {}, token=token)
        if not enabled or enabled.get("is_active") is not True:
            raise ValueError("Copilot Pipe was created but could not be enabled.")
    print("Copilot Pipe registered and enabled.")


if __name__ == "__main__":
    try:
        bootstrap()
    except (URLError, TimeoutError, ValueError) as exc:
        print(f"Open WebUI setup failed: {exc}", file=sys.stderr)
        sys.exit(1)

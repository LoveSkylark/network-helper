import os
import runpy
import sys


def configured_environment(environment):
    result = dict(environment)
    mode = result.get("OPENSEARCH_AUTH_MODE", "basic")
    if mode == "basic":
        result["OPENSEARCH_HEADER_AUTH"] = "false"
    elif mode in ("token", "api_key"):
        token = result.get("OPENSEARCH_TOKEN", "")
        if not token or any(character.isspace() for character in token):
            raise ValueError("OPENSEARCH_TOKEN must be a non-empty token without whitespace")
        result["OPENSEARCH_HEADER_AUTH"] = "true"
        result.pop("OPENSEARCH_USERNAME", None)
        result.pop("OPENSEARCH_PASSWORD", None)
    else:
        raise ValueError("OPENSEARCH_AUTH_MODE must be 'basic', 'token', or 'api_key'")
    result.pop("OPENSEARCH_TOKEN", None)
    return result


def api_key_headers(get_headers):
    def wrapped():
        headers = get_headers()
        authorization = headers.get("bearer_auth_header")
        if authorization and authorization.startswith("Bearer "):
            headers["bearer_auth_header"] = "ApiKey " + authorization[len("Bearer "):]
        return headers

    return wrapped


if __name__ == "__main__":
    try:
        environment = configured_environment(os.environ)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    os.environ.clear()
    os.environ.update(environment)
    if environment.get("OPENSEARCH_AUTH_MODE") == "api_key":
        import opensearch.client

        opensearch.client._get_auth_from_headers = api_key_headers(opensearch.client._get_auth_from_headers)
    sys.argv = ["mcp_server_opensearch", "--transport", "stream", "--host", "0.0.0.0", "--port", "9900"]
    runpy.run_module("mcp_server_opensearch", run_name="__main__")
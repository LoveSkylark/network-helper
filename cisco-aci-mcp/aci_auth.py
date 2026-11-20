import threading


def install_token_refresh(aci_client):
    original_make_request = aci_client.make_request
    refresh_lock = threading.Lock()

    def make_request(endpoint, method="GET", query_params=None, payload=None):
        expired_session = aci_client.session_cookies
        result = original_make_request(endpoint, method, query_params, payload)
        error = result.get("error", "") if isinstance(result, dict) else ""
        if (
            not isinstance(error, str)
            or not error.startswith(("HTTP 401:", "HTTP 403:"))
            or "token timeout" not in error.casefold()
        ):
            return result

        with refresh_lock:
            if aci_client.session_cookies is expired_session:
                aci_client.session_cookies = None
            if method.upper() == "GET":
                return original_make_request(endpoint, method, query_params, payload)
        return result

    aci_client.make_request = make_request

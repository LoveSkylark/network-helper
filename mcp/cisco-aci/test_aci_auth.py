import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from aci_auth import install_token_refresh


class TokenRefreshTests(unittest.TestCase):
    def setUp(self):
        self.request = Mock()
        self.client = SimpleNamespace(
            make_request=self.request,
            session_cookies=object(),
        )

    def test_expired_token_reauthenticates_and_retries_once(self):
        expired = {"error": "HTTP 403: Token timeout", "status": "error"}
        success = {"data": {"imdata": []}, "status": "success"}
        self.request.side_effect = [expired, success]
        install_token_refresh(self.client)

        result = self.client.make_request("/api/node/class/fvTenant.json")

        self.assertEqual(result, success)
        self.assertIsNone(self.client.session_cookies)
        self.assertEqual(self.request.call_count, 2)

    def test_other_forbidden_errors_are_not_retried(self):
        forbidden = {"error": "HTTP 403: Insufficient privileges", "status": "error"}
        self.request.return_value = forbidden
        install_token_refresh(self.client)
        session = self.client.session_cookies

        result = self.client.make_request("/api/node/class/fvTenant.json")

        self.assertEqual(result, forbidden)
        self.assertIs(self.client.session_cookies, session)
        self.assertEqual(self.request.call_count, 1)

    def test_retry_failure_is_returned(self):
        expired = {"error": "HTTP 403: Token timeout", "status": "error"}
        authentication_failed = {"error": "Authentication failed", "status": "error"}
        self.request.side_effect = [expired, authentication_failed]
        install_token_refresh(self.client)

        result = self.client.make_request("/api/node/class/fvTenant.json")

        self.assertEqual(result, authentication_failed)
        self.assertEqual(self.request.call_count, 2)

    def test_expired_cookie_is_cleared_without_replaying_a_write(self):
        expired = {"error": "HTTP 403: Token timeout", "status": "error"}
        self.request.return_value = expired
        install_token_refresh(self.client)

        self.assertEqual(self.client.make_request("/api/node/mo/example.json", "POST"), expired)
        self.assertIsNone(self.client.session_cookies)
        self.assertEqual(self.request.call_count, 1)

    def test_expired_response_does_not_clear_a_cookie_refreshed_in_parallel(self):
        replacement = object()

        def request(*args):
            self.client.session_cookies = replacement
            return {"error": "HTTP 403: Token timeout"}

        self.request.side_effect = request
        install_token_refresh(self.client)
        self.client.make_request("/api/node/mo/example.json", "POST")
        self.assertIs(self.client.session_cookies, replacement)


if __name__ == "__main__":
    unittest.main()

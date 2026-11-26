import json
import stat
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from register_acme_dns import register_account


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class AcmeDnsRegistrationTests(unittest.TestCase):
    @patch("register_acme_dns.urlopen")
    def test_registration_saves_domain_keyed_private_account_file(self, urlopen_mock):
        urlopen_mock.return_value = FakeResponse({
            "fulldomain": "id.auth.example.test",
            "subdomain": "id",
            "username": "fake-user",
            "password": "fake-password",
            "allowfrom": [],
        })
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "acme-dns-account.example.test.json"
            register_account(
                "Example.Test.",
                "https://auth.example.test",
                output_path,
            )

            request = urlopen_mock.call_args.args[0]
            self.assertEqual(request.full_url, "https://auth.example.test/register")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.data, b"")
            self.assertEqual(
                json.loads(output_path.read_text()),
                {
                    "example.test": {
                        "fulldomain": "id.auth.example.test",
                        "subdomain": "id",
                        "username": "fake-user",
                        "password": "fake-password",
                        "server_url": "https://auth.example.test",
                    }
                },
            )
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)

    @patch("register_acme_dns.urlopen")
    def test_invalid_server_url_is_rejected_before_registration(self, urlopen_mock):
        with self.assertRaises(ValueError):
            register_account(
                "example.test",
                "http://auth.example.test",
                ROOT / "acme-dns-account.example.test.json",
            )
        urlopen_mock.assert_not_called()

    @patch("register_acme_dns.urlopen")
    def test_existing_account_file_is_not_overwritten(self, urlopen_mock):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "account.json"
            output_path.write_text("existing")

            with self.assertRaises(FileExistsError):
                register_account(
                    "example.test",
                    "https://auth.example.test",
                    output_path,
                )

            self.assertEqual(output_path.read_text(), "existing")
            urlopen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

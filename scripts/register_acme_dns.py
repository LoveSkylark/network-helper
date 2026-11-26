#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ACCOUNT_FIELDS = ("fulldomain", "subdomain", "username", "password")


def register_account(domain: str, server_url: str, output_path: Path) -> None:
    domain = domain.rstrip(".").lower()
    if not re.fullmatch(
        r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
        domain,
    ):
        raise ValueError("Provide a fully qualified domain name.")

    parsed_url = urlsplit(server_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.path not in ("", "/"):
        raise ValueError("The ACME-DNS server URL must be an HTTPS origin.")
    if parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        raise ValueError("The ACME-DNS server URL must not contain credentials or query values.")
    server_url = server_url.rstrip("/")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing account file: {output_path}")
    request = Request(
        f"{server_url}/register",
        data=b"",
        headers={"Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        account_response = json.loads(response.read())

    if not isinstance(account_response, dict) or any(
        not isinstance(account_response.get(field), str) or not account_response[field]
        for field in ACCOUNT_FIELDS
    ):
        raise ValueError("The ACME-DNS registration response did not contain valid account data.")

    account = {field: account_response[field] for field in ACCOUNT_FIELDS}
    account["server_url"] = server_url
    account_file = {domain: account}

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as output:
            json.dump(account_file, output, indent=4)
            output.write("\n")
    except OSError:
        output_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register an ACME-DNS account and save its private account file."
    )
    parser.add_argument("--domain", required=True, help="FQDN to authorize with ACME-DNS")
    parser.add_argument("--server-url", required=True, help="HTTPS ACME-DNS server origin")
    parser.add_argument("--output", required=True, type=Path, help="Private JSON account-file path")
    args = parser.parse_args()

    register_account(args.domain, args.server_url, args.output)
    print(f"ACME-DNS account file written to {args.output}. Keep it private.")


if __name__ == "__main__":
    main()

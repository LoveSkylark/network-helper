import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = (ROOT / "compose.yaml", ROOT / "compose.podman.yaml")
EXAMPLE_ENV = ROOT / ".env.example"
LIBRECHAT_CONFIG = ROOT / "librechat" / "librechat.yaml"
LITELLM_CONFIG = ROOT / "litellm" / "config.yaml"
VARIABLE = re.compile(r"(?<!\$)\$(?:\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))")
ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)
MCP_SERVICES = {
    "fortios-mcp",
    "opensearch-mcp",
    "cisco-aci-mcp",
    "netbox-mcp",
    "librenms-mcp",
}


def referenced_variables():
    return {
        braced or unbraced
        for path in COMPOSE_FILES
        for braced, unbraced in VARIABLE.findall(path.read_text())
    }


def render_compose(runtime, *, podman_override, overrides=None):
    variables = referenced_variables() | set(ENV_KEY.findall(EXAMPLE_ENV.read_text()))
    variables.update({
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_ENV_FILES",
        "COMPOSE_DISABLE_ENV_FILE",
        "COMPOSE_PATH_SEPARATOR",
    })
    environment = {key: value for key, value in os.environ.items() if key not in variables}
    if overrides:
        environment.update(overrides)
    command = [
        runtime,
        "compose",
        "--env-file",
        str(EXAMPLE_ENV),
        "-f",
        str(COMPOSE_FILES[0]),
    ]
    if podman_override:
        command.extend(["-f", str(COMPOSE_FILES[1])])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


class ComposeConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = os.environ.get("COMPOSE_RUNTIME")
        if runtime is None:
            runtime = shutil.which("podman") or shutil.which("docker")
        if runtime is None:
            raise RuntimeError("Install Podman or Docker with Compose, or set COMPOSE_RUNTIME.")
        cls.runtime = runtime
        cls.base = render_compose(runtime, podman_override=False)
        cls.podman = render_compose(runtime, podman_override=True)

    def test_example_environment_covers_compose_variables(self):
        provided = set(ENV_KEY.findall(EXAMPLE_ENV.read_text()))
        self.assertEqual(referenced_variables() - provided, set())

    def test_librechat_urls_follow_hostname(self):
        config = render_compose(
            self.runtime,
            podman_override=False,
            overrides={
                "LIBRECHAT_HOSTNAME": "portal.example.test",
                "DOMAIN_CLIENT": "https://old-client.example.test",
                "DOMAIN_SERVER": "https://old-server.example.test",
            },
        )
        service = config["services"]["librechat"]
        self.assertEqual(service["environment"]["DOMAIN_CLIENT"], "https://portal.example.test")
        self.assertEqual(service["environment"]["DOMAIN_SERVER"], "https://portal.example.test")
        self.assertEqual(
            service["labels"]["traefik.http.routers.librechat.rule"],
            "Host(`portal.example.test`)",
        )

    def test_local_login_is_enabled_without_public_registration(self):
        environment = self.base["services"]["librechat"]["environment"]
        self.assertEqual(environment["ALLOW_EMAIL_LOGIN"], "true")
        self.assertEqual(environment["ALLOW_REGISTRATION"], "false")
        self.assertEqual(environment["ALLOW_SOCIAL_LOGIN"], "false")

        config = render_compose(
            self.runtime,
            podman_override=False,
            overrides={"ALLOW_EMAIL_LOGIN": "false", "ALLOW_SOCIAL_LOGIN": "true"},
        )
        environment = config["services"]["librechat"]["environment"]
        self.assertEqual(environment["ALLOW_EMAIL_LOGIN"], "false")
        self.assertEqual(environment["ALLOW_SOCIAL_LOGIN"], "true")
        self.assertEqual(environment["ALLOW_REGISTRATION"], "false")

    def test_internal_database_identities_are_consistent(self):
        config = render_compose(
            self.runtime,
            podman_override=False,
            overrides={
                "MONGO_ROOT_USERNAME": "old-user",
                "POSTGRES_USER": "old-user",
                "POSTGRES_DB": "old-db",
            },
        )
        services = config["services"]
        self.assertEqual(
            services["mongodb"]["environment"]["MONGO_INITDB_ROOT_USERNAME"], "librechat"
        )
        self.assertTrue(
            services["librechat"]["environment"]["MONGO_URI"].startswith("mongodb://librechat:")
        )
        for service in ("vectordb", "rag-api"):
            with self.subTest(service=service):
                environment = services[service]["environment"]
                self.assertEqual(environment["POSTGRES_USER"], "librechat")
                self.assertEqual(environment["POSTGRES_DB"], "librechat")

    def test_only_traefik_publishes_port_443(self):
        services = self.base["services"]
        published = {
            name: service["ports"]
            for name, service in services.items()
            if service.get("ports")
        }
        self.assertEqual(set(published), {"traefik"})
        self.assertEqual(len(published["traefik"]), 1)
        port = published["traefik"][0]
        self.assertEqual(str(port["published"]), "443")
        self.assertEqual(port["target"], 443)

    def test_librechat_is_the_only_configured_portal(self):
        for config in (self.base, self.podman):
            services = config["services"]
            self.assertNotIn("open-webui", services)
            routed_services = {
                name
                for name, service in services.items()
                if any(label.startswith("traefik.http.routers.") for label in service.get("labels", {}))
            }
            self.assertEqual(routed_services, {"librechat"})

    def test_traefik_routes_librechat_with_tls(self):
        services = self.base["services"]
        traefik = services["traefik"]
        librechat = services["librechat"]
        self.assertFalse(librechat.get("ports"))
        self.assertEqual(set(traefik["networks"]), {"proxy-net"})
        self.assertIn("proxy-net", librechat["networks"])
        self.assertEqual(
            self.base["networks"]["proxy-net"]["name"],
            "network-helper-proxy-net",
        )
        self.assertIn(
            "--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=acme-dns",
            traefik["command"],
        )
        self.assertTrue(
            any(
                argument.startswith("--certificatesresolvers.letsencrypt.acme.email=")
                for argument in traefik["command"]
            )
        )
        self.assertEqual(
            librechat["labels"]["traefik.http.routers.librechat.tls"],
            "true",
        )
        self.assertEqual(
            librechat["labels"]["traefik.http.routers.librechat.tls.certresolver"],
            "letsencrypt",
        )
        self.assertEqual(
            traefik["environment"]["ACME_DNS_STORAGE_PATH"],
            "/etc/traefik/acme-dns-account.json",
        )
        self.assertTrue(
            any(
                mount.get("target") == "/etc/traefik/acme-dns-account.json"
                and mount.get("read_only")
                for mount in traefik["volumes"]
            )
        )
        self.assertEqual(
            librechat["labels"]["traefik.http.routers.librechat.rule"],
            "Host(`chat.example.com`)",
        )

    def test_mcp_services_keep_dedicated_private_networks(self):
        services = self.base["services"]
        networks = []
        for name in MCP_SERVICES:
            with self.subTest(service=name):
                attached = set(services[name].get("networks", {}))
                self.assertEqual(len(attached), 1)
                networks.extend(attached)
        self.assertEqual(len(networks), len(set(networks)))
        self.assertEqual(set(services["librechat"]["networks"]) & set(networks), set(networks))
        self.assertNotIn("cisco-ise-mcp", services)
        self.assertTrue(set(services["litellm"]["networks"]).isdisjoint(networks))

    def test_librenms_tool_search_preserves_read_only_mode(self):
        environment = self.base["services"]["librenms-mcp"]["environment"]
        self.assertEqual(environment["READ_ONLY_MODE"], "true")
        self.assertEqual(environment["TOOL_SEARCH_ENABLED"], "true")

    def test_librechat_cannot_reach_the_copilot_adapter_directly(self):
        services = self.base["services"]
        librechat_networks = set(services["librechat"]["networks"])
        adapter_networks = set(services["copilot-adapter"]["networks"])
        gateway_networks = set(services["litellm"]["networks"])
        self.assertTrue(librechat_networks.isdisjoint(adapter_networks))
        self.assertIn("gateway-client-net", librechat_networks & gateway_networks)
        self.assertIn("litellm-upstream-net", adapter_networks & gateway_networks)
        self.assertNotIn("ollama-net", librechat_networks)
        database_network = set(services["litellm-db"]["networks"])
        self.assertEqual(database_network, {"litellm-db-net"})
        self.assertTrue(self.base["networks"]["litellm-db-net"]["internal"])
        self.assertEqual(
            {
                name
                for name, service in services.items()
                if "litellm-db-net" in service.get("networks", {})
            },
            {"litellm", "litellm-db"},
        )

    def test_librechat_mcp_targets_match_active_services(self):
        targets = {
            urlparse(url).hostname
            for url in re.findall(r"^\s+url:\s+(http://\S+)", LIBRECHAT_CONFIG.read_text(), re.M)
        }
        self.assertEqual(targets, MCP_SERVICES)

    def test_opensearch_auth_configuration(self):
        for mode in ("basic", "token", "api_key"):
            config = render_compose(
                self.runtime,
                podman_override=False,
                overrides={"OPENSEARCH_AUTH_MODE": mode, "OPENSEARCH_TOKEN": "test-token"},
            )
            services = config["services"]
            self.assertEqual(services["opensearch-mcp"]["environment"]["OPENSEARCH_AUTH_MODE"], mode)
            self.assertEqual(services["opensearch-mcp"]["environment"]["OPENSEARCH_TOKEN"], "test-token")
            self.assertEqual(services["librechat"]["environment"]["OPENSEARCH_TOKEN"], "test-token")
        self.assertIn('Authorization: "Bearer ${OPENSEARCH_TOKEN}"', LIBRECHAT_CONFIG.read_text())

    def test_mcp_approval_policy_defaults_to_review(self):
        config = LIBRECHAT_CONFIG.read_text()
        self.assertEqual(config.count("chatMenu: false"), len(MCP_SERVICES))
        policy = re.search(
            r"(?ms)^    toolApproval:\n(?P<body>(?:^      .*\n)*)", config
        )
        self.assertIsNotNone(policy)
        body = policy.group("body")
        self.assertIn("      enabled: true\n", body)
        self.assertIn("      mode: default\n", body)
        self.assertNotRegex(body, r"(?m)^      (?:ask|deny):")
        self.assertEqual(set(re.findall(r"(?m)^        - (\S+)$", body)), {
            "search_tools_mcp_fortios",
            "search_tools_mcp_cisco-aci",
            "search_tools_mcp_librenms",
            "cmdb_list_mcp_fortios",
            "cmdb_get_mcp_fortios",
            "monitor_get_mcp_fortios",
            "log_get_mcp_fortios",
        })

    def test_litellm_blocks_cloud_tool_calls_and_routes_local_model(self):
        config = LITELLM_CONFIG.read_text()
        self.assertIn("model_name: copilot-auto", config)
        self.assertIn("model_name: local-ollama", config)
        self.assertIn("guardrail: local_only_mcp.LocalOnlyMcpGuardrail", config)
        self.assertIn("default_on: true", config)
        services = self.base["services"]
        self.assertEqual(services["litellm"]["environment"]["ALLOW_COPILOT_MCP"], "false")
        self.assertEqual(services["copilot-adapter"]["environment"]["ALLOW_COPILOT_MCP"], "false")

    def test_example_environment_uses_separate_litellm_keys(self):
        services = self.base["services"]
        self.assertNotEqual(
            services["litellm"]["environment"]["LITELLM_MASTER_KEY"],
            services["librechat"]["environment"]["LITELLM_VIRTUAL_KEY"],
        )
        self.assertEqual(
            services["litellm-key-init"]["environment"]["LITELLM_VIRTUAL_KEY"],
            services["librechat"]["environment"]["LITELLM_VIRTUAL_KEY"],
        )

    def test_podman_override_preserves_services_and_isolates_mcp_networks(self):
        services = self.base["services"]
        self.assertEqual(set(self.podman["services"]), set(services))
        for name, service in services.items():
            with self.subTest(service=name):
                overridden = self.podman["services"][name]
                self.assertEqual(set(overridden["networks"]), set(service["networks"]))
                self.assertEqual(overridden.get("ports"), service.get("ports"))

        for name in MCP_SERVICES:
            network = next(iter(services[name]["networks"]))
            with self.subTest(network=network):
                base_network = self.base["networks"][network]
                isolated_network = self.podman["networks"][network]
                self.assertNotIn("isolate", base_network.get("driver_opts", {}))
                self.assertEqual(str(isolated_network["driver_opts"]["isolate"]), "1")
                self.assertFalse(isolated_network.get("internal", False))


if __name__ == "__main__":
    unittest.main()

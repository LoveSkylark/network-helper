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
VARIABLE = re.compile(r"(?<!\$)\$(?:\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))")
ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)


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

    def test_compose_uses_example_webui_url(self):
        values = dict(
            line.split("=", 1)
            for line in EXAMPLE_ENV.read_text().splitlines()
            if line.startswith("WEBUI_URL=")
        )
        url = values["WEBUI_URL"]
        environment = self.base["services"]["open-webui"]["environment"]
        self.assertEqual(environment["WEBUI_URL"], url)
        self.assertEqual(environment["MICROSOFT_REDIRECT_URI"], f"{url}/oauth/microsoft/callback")

    def test_only_webui_publishes_port_80(self):
        services = self.base["services"]
        published = {
            name: service["ports"]
            for name, service in services.items()
            if service.get("ports")
        }
        self.assertEqual(set(published), {"open-webui"})
        self.assertEqual(len(published["open-webui"]), 1)
        port = published["open-webui"][0]
        self.assertEqual(str(port["published"]), "80")
        self.assertEqual(port["target"], 8080)
        self.assertIn(port.get("host_ip", ""), ("", "0.0.0.0", "::"))
        self.assertEqual(port.get("protocol", "tcp"), "tcp")

    def test_mcp_network_subnets_are_allocated_by_runtime(self):
        for config in (self.base, self.podman):
            for name, network in config["networks"].items():
                with self.subTest(network=name):
                    self.assertFalse(network.get("ipam", {}).get("config"))

    def test_mcp_services_have_dedicated_webui_networks(self):
        services = self.base["services"]
        mcp_services = {
            name: service for name, service in services.items()
            if name not in {"open-webui", "copilot-pipe-init"}
        }
        self.assertTrue(mcp_services)
        networks = []
        for name, service in mcp_services.items():
            with self.subTest(service=name):
                attached = set(service.get("networks", {}))
                self.assertEqual(len(attached), 1)
                networks.extend(attached)
        self.assertEqual(len(networks), len(set(networks)))
        self.assertEqual(set(services["open-webui"]["networks"]) - {"webui-bootstrap-net"}, set(networks))

        connections = json.loads(services["open-webui"]["environment"]["TOOL_SERVER_CONNECTIONS"])
        targets = {urlparse(connection["url"]).hostname for connection in connections}
        self.assertEqual(targets, set(mcp_services))

    def test_pipe_initializer_waits_for_webui_on_a_private_network(self):
        for config in (self.base, self.podman):
            services = config["services"]
            init = services["copilot-pipe-init"]
            self.assertEqual(init["depends_on"]["open-webui"]["condition"], "service_healthy")
            self.assertEqual(init["image"], services["open-webui"]["image"])
            self.assertEqual(set(init["networks"]), {"webui-bootstrap-net"})
            self.assertIn("webui-bootstrap-net", services["open-webui"]["networks"])
            self.assertTrue(config["networks"]["webui-bootstrap-net"]["internal"])

    def test_bundled_mcp_connections_are_shared_with_signed_in_users(self):
        for config in (self.base, self.podman):
            services = config["services"]
            defaults = services["open-webui"]["environment"]["TOOL_SERVER_CONNECTIONS"]
            self.assertEqual(services["copilot-pipe-init"]["environment"]["TOOL_SERVER_CONNECTIONS"], defaults)
            for connection in json.loads(defaults):
                with self.subTest(server=connection["info"]["id"]):
                    self.assertEqual(
                        connection["config"]["access_grants"],
                        [{"principal_type": "user", "principal_id": "*", "permission": "read"}],
                    )

    def test_podman_override_isolates_each_mcp_network(self):
        services = self.base["services"]
        self.assertEqual(set(self.podman["services"]), set(services))
        for name, service in services.items():
            with self.subTest(service=name):
                overridden = self.podman["services"][name]
                self.assertEqual(set(overridden["networks"]), set(service["networks"]))
                self.assertEqual(overridden.get("ports"), service.get("ports"))
        networks = {
            network
            for name, service in services.items()
            if name not in {"open-webui", "copilot-pipe-init"}
            for network in service["networks"]
        }
        for network in networks:
            with self.subTest(network=network):
                base = self.base["networks"][network]
                isolated = self.podman["networks"][network]
                self.assertNotIn("isolate", base.get("driver_opts", {}))
                self.assertEqual(str(isolated["driver_opts"]["isolate"]), "1")
                self.assertFalse(isolated.get("internal", False))


if __name__ == "__main__":
    unittest.main()

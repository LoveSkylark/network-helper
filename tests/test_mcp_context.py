import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("build_mcp_context", ROOT / "scripts/build_mcp_context.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SERVER_NAMES = ("fortios", "opensearch", "cisco-aci", "netbox", "librenms")


class McpContextTests(unittest.TestCase):
    def test_repository_context_matches_all_configured_servers(self):
        config_path = ROOT / "librechat/librechat.yaml"
        config = MODULE.build_config(config_path, ROOT / "network-context")
        self.assertEqual(set(config["mcpServers"]), set(SERVER_NAMES))
        for name in SERVER_NAMES:
            self.assertTrue(config["mcpServers"][name].pop("serverInstructions"))
        self.assertEqual(config, yaml.safe_load(config_path.read_text(encoding="utf-8")))

    def test_build_config_attaches_only_matching_server_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = directory / "librechat.yaml"
            config_path.write_text(yaml.safe_dump({
                "mcpServers": {name: {"url": f"http://{name}:8000/mcp"} for name in SERVER_NAMES},
                "apiKey": "${LITELLM_VIRTUAL_KEY}",
            }), encoding="utf-8")
            for name in SERVER_NAMES:
                (directory / f"{name}.md").write_text(f"Context for {name}\n", encoding="utf-8")

            config = MODULE.build_config(config_path, directory)

            for name in SERVER_NAMES:
                self.assertEqual(config["mcpServers"][name]["serverInstructions"], f"Context for {name}\n")
                self.assertEqual(config["mcpServers"][name]["url"], f"http://{name}:8000/mcp")
            self.assertEqual(config["apiKey"], "${LITELLM_VIRTUAL_KEY}")

    def test_missing_empty_and_oversized_context_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = directory / "librechat.yaml"
            config_path.write_text(yaml.safe_dump({
                "mcpServers": {name: {} for name in SERVER_NAMES},
            }), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                MODULE.build_config(config_path, directory)
            for name in SERVER_NAMES:
                (directory / f"{name}.md").write_text("context", encoding="utf-8")
            context_path = directory / f"{SERVER_NAMES[0]}.md"
            for invalid in ("", "   ", "x" * (MODULE.MAX_CONTEXT_BYTES + 1)):
                with self.subTest(length=len(invalid)):
                    context_path.write_text(invalid, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        MODULE.build_config(config_path, directory)

    def test_additional_named_server_uses_its_own_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = directory / "librechat.yaml"
            config_path.write_text(yaml.safe_dump({
                "mcpServers": {"fortios-site-b": {"url": "http://fortios-site-b:8000/mcp"}},
            }), encoding="utf-8")
            (directory / "fortios-site-b.md").write_text("Site B context", encoding="utf-8")
            config = MODULE.build_config(config_path, directory)
            self.assertEqual(config["mcpServers"]["fortios-site-b"]["serverInstructions"], "Site B context")

    def test_invalid_server_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = directory / "librechat.yaml"
            config_path.write_text(yaml.safe_dump({"mcpServers": {"../outside": {}}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.build_config(config_path, directory)


if __name__ == "__main__":
    unittest.main()
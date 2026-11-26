import argparse
from pathlib import Path
import re

import yaml


SERVER_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_CONTEXT_BYTES = 65536


def build_config(config_path, context_dir):
    with config_path.open(encoding="utf-8") as source:
        config = yaml.safe_load(source)

    for server_name in config["mcpServers"]:
        if not SERVER_NAME.fullmatch(server_name):
            raise ValueError(f"Invalid MCP server name: {server_name}")
        context_path = context_dir / f"{server_name}.md"
        context_bytes = context_path.read_bytes()
        if not context_bytes or len(context_bytes) > MAX_CONTEXT_BYTES:
            raise ValueError(f"Invalid context size: {context_path}")
        context = context_bytes.decode("utf-8")
        if not context.strip():
            raise ValueError(f"Empty context: {context_path}")
        config["mcpServers"][server_name]["serverInstructions"] = context

    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--context-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = build_config(args.config, args.context_dir)
    with args.output.open("w", encoding="utf-8") as output:
        yaml.safe_dump(config, output, sort_keys=False, allow_unicode=True)


if __name__ == "__main__":
    main()
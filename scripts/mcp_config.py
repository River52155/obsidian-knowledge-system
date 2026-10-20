#!/usr/bin/env python3
"""Print MCP stdio configuration; never reads notes or edits client settings."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    vault = args.vault.expanduser().resolve()
    if not vault.is_dir():
        parser.error('--vault must be an existing directory')
    project = Path(__file__).resolve().parents[1] / 'personal-memory'
    python = project / '.venv' / 'bin' / 'python'
    if not python.is_file():
        parser.error('Create personal-memory/.venv and install requirements first')
    print(json.dumps({'mcpServers': {'personal-memory': {
        'command': str(python),
        'args': [str(project / 'mcp_bridge.py'), '--vault', str(vault), '--port', str(args.port)]
    }}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

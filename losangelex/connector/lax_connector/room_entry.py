"""Conversational CLI without importing the retired claimed-work runtime."""
import argparse
import asyncio
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--serve', action='store_true', required=True)
    args = parser.parse_args()
    from .runtime_files import private_file
    private_file(args.config)
    config = json.loads(args.config.read_text())
    from .runtime_mode import require_worker_context
    if require_worker_context(config) != 'room-conversation':
        parser.error('This entrypoint serves only the explicitly enrolled room context')
    from .conversational_agent import ConversationalAgent
    asyncio.run(ConversationalAgent(config).serve())


if __name__ == '__main__':
    main()

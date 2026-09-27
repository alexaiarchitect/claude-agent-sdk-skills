"""`python -m agent_sdk_evals ...` — the only entry point the plugin uses."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

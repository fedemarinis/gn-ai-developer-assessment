"""Allows `python -m agent` to start the CLI."""

import sys

from agent.cli import main

sys.exit(main())

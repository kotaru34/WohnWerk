"""Manual diagnostic discovery at immobilien.de; not scheduled."""
import asyncio

from scripts.run_public_portal_de import run_portal


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_portal("immobilien-de")))

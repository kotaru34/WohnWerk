"""Manual diagnostic discovery at ohne-makler.net; not scheduled."""
import asyncio

from run_public_portal_de import run_portal


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_portal("ohne-makler-de")))

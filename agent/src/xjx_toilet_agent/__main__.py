"""CLI entrypoints."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .service import AgentService
from .toilet import ToiletClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xjx-toilet-agent")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status"],
        help="run: MQTT agent; status: one-shot poll",
    )
    args = parser.parse_args(argv)
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.toilet_token:
        print("TOILET_TOKEN is required", file=sys.stderr)
        return 2

    if args.command == "status":
        client = ToiletClient(
            settings.toilet_host,
            settings.toilet_token,
            timeout=settings.miio_timeout,
            poll_gap=settings.poll_gap_sec,
        )
        state = client.poll_full()
        print(state.to_mqtt())
        return 0 if state.online else 1

    if not settings.mqtt_host:
        print("MQTT_HOST is required for run", file=sys.stderr)
        return 2

    AgentService(settings).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

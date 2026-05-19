from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Sequence

from .config import load_config
from .inbox import InboxProcessor
from .payloads import request_from_payload
from .router import AgentRouter
from .server import serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-hub")
    parser.add_argument(
        "--config",
        default="agent-hub.config.json",
        help="Path to the hub config JSON file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the local HTTP hub.")
    serve_parser.add_argument("--host", help="Override configured host.")
    serve_parser.add_argument("--port", type=int, help="Override configured port.")
    serve_parser.add_argument(
        "--watch-inbox",
        action="store_true",
        help="Also process JSON files from the configured inbox directory.",
    )

    watch_parser = subparsers.add_parser("watch", help="Process JSON files forever.")
    watch_parser.add_argument("--interval", type=float, default=1.0)

    subparsers.add_parser("once", help="Process the JSON inbox once.")

    route_parser = subparsers.add_parser("route", help="Route one JSON file and print the result.")
    route_parser.add_argument("path")
    route_parser.add_argument(
        "--api-shape",
        choices=["native", "openai-chat", "anthropic-messages"],
        default="native",
    )

    args = parser.parse_args(argv)
    config = load_config(args.config)
    if getattr(args, "host", None):
        config.host = args.host
    if getattr(args, "port", None):
        config.port = args.port
    config.ensure_dirs()

    command = args.command or "serve"
    if command == "serve":
        if getattr(args, "watch_inbox", False):
            processor = InboxProcessor(config)
            thread = threading.Thread(target=processor.watch, daemon=True)
            thread.start()
        serve(config)
        return 0
    if command == "watch":
        InboxProcessor(config).watch(interval_seconds=args.interval)
        return 0
    if command == "once":
        outputs = InboxProcessor(config).process_once()
        for output in outputs:
            print(output)
        return 0
    if command == "route":
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
        request = request_from_payload(payload, api_shape=args.api_shape)
        response = AgentRouter(config).route(request)
        print(json.dumps(response.to_native_dict(), indent=2, ensure_ascii=False))
        return 0
    parser.error(f"Unknown command {command!r}")
    return 2

"""Wyoming proxy that preprocesses Synthesize text before forwarding to Piper.

Architecture:

    HA  ──Synthesize(text)─▶  THIS PROXY  ──Synthesize(text')─▶  Piper(:10200)
    HA  ◀──audio chunks────       │       ◀──audio chunks───────  Piper

The proxy is a transparent Wyoming event forwarder. Every event passes
through unchanged EXCEPT a `Synthesize` event, whose `text` field is
rewritten using `preproc.preprocess()` before being sent to the upstream
Piper instance.

One inbound TCP connection → one upstream TCP connection (Wyoming-Piper
sessions are short-lived: one Describe-or-Synthesize, optional Info
response, audio stream, close).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from wyoming.event import async_read_event, async_write_event
from wyoming.tts import Synthesize

from .preproc import preprocess

_LOG = logging.getLogger("wyoming_piper_preproc")


async def _forward(
    src_reader: asyncio.StreamReader,
    dst_writer: asyncio.StreamWriter,
    intercept: bool,
    csv_paths: list[Path],
) -> None:
    """Forward events from src to dst. If intercept=True, rewrite Synthesize.text."""
    try:
        while True:
            event = await async_read_event(src_reader)
            if event is None:
                return
            if intercept and Synthesize.is_type(event.type):
                syn = Synthesize.from_event(event)
                original = syn.text
                rewritten = preprocess(original, csv_paths)
                if rewritten != original:
                    _LOG.info("rewrote: %r -> %r", original, rewritten)
                syn.text = rewritten
                event = syn.event()
            await async_write_event(event, dst_writer)
    except (ConnectionResetError, BrokenPipeError):
        return
    except Exception:
        _LOG.exception("forwarder error")
    finally:
        try:
            dst_writer.close()
        except Exception:
            pass


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    upstream_host: str,
    upstream_port: int,
    csv_paths: list[Path],
) -> None:
    peer = writer.get_extra_info("peername")
    _LOG.debug("client connected: %s", peer)
    try:
        up_reader, up_writer = await asyncio.open_connection(
            upstream_host, upstream_port
        )
    except (OSError, asyncio.TimeoutError) as e:
        _LOG.error("upstream %s:%d unreachable: %s", upstream_host, upstream_port, e)
        writer.close()
        return

    await asyncio.gather(
        _forward(reader, up_writer, intercept=True, csv_paths=csv_paths),
        _forward(up_reader, writer, intercept=False, csv_paths=csv_paths),
    )
    _LOG.debug("client closed: %s", peer)


async def _amain(args: argparse.Namespace) -> None:
    csv_paths = [Path(p) for p in args.pronunciations]

    server = await asyncio.start_server(
        lambda r, w: _handle_client(
            r, w, args.upstream_host, args.upstream_port, csv_paths
        ),
        host=args.host,
        port=args.port,
    )
    sockets = ", ".join(str(s.getsockname()) for s in server.sockets)
    _LOG.info("listening on %s, forwarding to %s:%d", sockets, args.upstream_host, args.upstream_port)
    _LOG.info("pronunciation files: %s", [str(p) for p in csv_paths])
    async with server:
        await server.serve_forever()


def main() -> None:
    p = argparse.ArgumentParser(prog="wyoming-piper-preproc")
    p.add_argument("--host", default=os.environ.get("LISTEN_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("LISTEN_PORT", "10210")))
    p.add_argument("--upstream-host", default=os.environ.get("UPSTREAM_HOST", "127.0.0.1"))
    p.add_argument("--upstream-port", type=int, default=int(os.environ.get("UPSTREAM_PORT", "10200")))
    p.add_argument(
        "--pronunciations",
        nargs="*",
        default=os.environ.get(
            "PRONUNCIATIONS",
            "/data/pronunciations.csv:/data/pronunciations-piper.csv",
        ).split(":"),
        help="One or more CSV files of pronunciation overrides, applied in order (later wins)",
    )
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(_amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

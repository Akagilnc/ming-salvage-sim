"""Package desktop/browser entry; both modes use the same loopback ASGI app."""

import argparse
import asyncio
import errno
import os
import socket
import sys
import threading
import webbrowser
from concurrent.futures import Future
from collections.abc import Callable
from typing import cast
from pathlib import Path

import uvicorn

from ming.middle.cli_model import wait_until_started
from ming.web import Web, create_app


class Server(uvicorn.Server):
    web: Web

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # Finish accepted player actions before closing SSE connections or SQLite.
        await self.web.close()
        await super().shutdown(sockets)


def main() -> None:
    parser = argparse.ArgumentParser(description="残明朱批：新包本地网页入口")
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".ming" / "saves"
    )
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--desktop", action="store_true", default=bool(getattr(sys, "frozen", False))
    )
    args = parser.parse_args()
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", args.port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            listener.bind(("127.0.0.1", 0))
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        app = create_app(args.directory, static=root / "web" / "dist")
        server = Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=listener.getsockname()[1], log_config=None
            )
        )
        server.web = app.state.web
        result: Future[None] = Future()

        def serve() -> None:
            try:
                server.run(sockets=[listener])
            except BaseException as error:
                result.set_exception(error)
            else:
                result.set_result(None)

        thread = threading.Thread(target=serve, name="ming-asgi")
        thread.start()

        async def failed() -> None:
            result.result()

        try:
            asyncio.run(
                wait_until_started(server, result.done, asyncio.sleep, failed)
            )
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            if args.desktop:
                import webview

                create_window = cast(
                    Callable[..., object], getattr(webview, "create_window")
                )
                create_window(
                    "残明朱批：崇祯", url, width=1366, height=880, min_size=(1024, 720)
                )
                webview.start(debug=bool(os.environ.get("MING_DEBUG")))
            else:
                webbrowser.open(url)
                thread.join()
        except KeyboardInterrupt:
            pass  # User-requested normal shutdown, not a failed game action.
        finally:
            server.should_exit = True
            thread.join()
        result.result()


if __name__ == "__main__":
    main()

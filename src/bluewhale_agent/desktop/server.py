"""Bounded lifecycle control for the desktop loopback server."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI


class DesktopServerError(RuntimeError):
    """Raised when the desktop HTTP server cannot start or stop safely."""


ServerFactory = Callable[[uvicorn.Config], uvicorn.Server]
SocketFactory = Callable[[int, int], socket.socket]


class LocalServerController:
    """Run Uvicorn on a pre-bound random loopback port."""

    def __init__(
        self,
        app: FastAPI,
        *,
        startup_timeout: float = 10.0,
        server_factory: ServerFactory = uvicorn.Server,
        socket_factory: SocketFactory = socket.socket,
    ) -> None:
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be positive")
        self._app = app
        self._startup_timeout = startup_timeout
        self._server_factory = server_factory
        self._socket_factory = socket_factory
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._thread_error: BaseException | None = None

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def port(self) -> int:
        if self._socket is None:
            raise DesktopServerError("Desktop server is not started")
        return int(self._socket.getsockname()[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return bool(
            self._server is not None
            and self._server.started
            and self._thread is not None
            and self._thread.is_alive()
        )

    def start(self) -> None:
        if self.running:
            return
        bound_socket = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            bound_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound_socket.bind((self.host, 0))
            bound_socket.listen(128)
        except BaseException:
            bound_socket.close()
            raise
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=0,
            log_level="warning",
            access_log=False,
        )
        server = self._server_factory(config)
        self._socket = bound_socket
        self._server = server
        self._thread_error = None

        def serve() -> None:
            try:
                asyncio.run(server.serve(sockets=[bound_socket]))
            except BaseException as error:
                self._thread_error = error

        thread = threading.Thread(target=serve, name="bluewhale-desktop-server")
        self._thread = thread
        thread.start()
        deadline = time.monotonic() + self._startup_timeout
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            self._abort_start()
            if self._thread_error is not None:
                raise DesktopServerError("Desktop server failed to start") from self._thread_error
            raise DesktopServerError("Desktop server did not start in time")

    def stop(self, timeout: float = 5.0) -> None:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        server = self._server
        thread = self._thread
        if server is None or thread is None:
            return
        server.should_exit = True
        thread.join(timeout)
        if thread.is_alive():
            raise DesktopServerError("Desktop server did not stop in time")
        self._close_socket()
        self._server = None
        self._thread = None

    def _abort_start(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(1)
        self._close_socket()
        self._server = None
        self._thread = None

    def _close_socket(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

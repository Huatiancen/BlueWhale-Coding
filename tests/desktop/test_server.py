from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from bluewhale_agent.desktop.server import DesktopServerError, LocalServerController


def health_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


class FakeSocket:
    def __init__(self) -> None:
        self.bound: tuple[str, int] | None = None
        self.backlog: int | None = None
        self.closed = False

    def setsockopt(self, _level: int, _option: int, _value: int) -> None:
        return None

    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address

    def listen(self, backlog: int) -> None:
        self.backlog = backlog

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 43210)

    def close(self) -> None:
        self.closed = True


class FakeServer:
    def __init__(self, _config: object) -> None:
        self.started = False
        self.should_exit = False

    async def serve(self, *, sockets: list[object]) -> None:
        assert sockets
        self.started = True
        while not self.should_exit:
            await asyncio.sleep(0.001)


def controller_with_fakes() -> tuple[LocalServerController, FakeSocket]:
    fake_socket = FakeSocket()
    controller = LocalServerController(
        health_app(),
        startup_timeout=1,
        server_factory=FakeServer,
        socket_factory=lambda _family, _kind: fake_socket,  # type: ignore[arg-type]
    )
    return controller, fake_socket


def test_controller_uses_random_loopback_port_and_stops_cleanly() -> None:
    controller, fake_socket = controller_with_fakes()

    controller.start()
    assert controller.host == "127.0.0.1"
    assert controller.port == 43210
    assert controller.base_url == "http://127.0.0.1:43210"
    assert fake_socket.bound == ("127.0.0.1", 0)
    assert fake_socket.backlog == 128
    controller.stop()

    assert controller.running is False
    assert fake_socket.closed is True


def test_controller_start_and_stop_are_idempotent() -> None:
    controller, _ = controller_with_fakes()

    controller.start()
    first_port = controller.port
    controller.start()
    assert controller.port == first_port
    controller.stop()
    controller.stop()


def test_controller_rejects_invalid_timeouts() -> None:
    with pytest.raises(ValueError, match="startup_timeout"):
        LocalServerController(health_app(), startup_timeout=0)

    controller = LocalServerController(health_app())
    with pytest.raises(ValueError, match="timeout"):
        controller.stop(timeout=-1)
    with pytest.raises(DesktopServerError, match="not started"):
        _ = controller.port


def test_real_controller_runs_app_shutdown_lifespan() -> None:
    shutdown_complete = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        shutdown_complete.set()

    controller = LocalServerController(FastAPI(lifespan=lifespan))

    try:
        controller.start()
    except PermissionError:
        pytest.skip("environment does not permit binding a loopback test socket")
    controller.stop()

    assert shutdown_complete.is_set()
    assert not any(
        thread.name == "bluewhale-desktop-server" and thread.is_alive()
        for thread in threading.enumerate()
    )

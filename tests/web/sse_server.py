import contextlib
import socket
import threading
import time

import uvicorn


@contextlib.contextmanager
def run_server(app, sock: socket.socket):
    """Run uvicorn in a background thread on a pre-bound loopback socket.

    Two deliberate choices keep this deterministic and off deprecated APIs:

    - We bind the socket ourselves and hand it to uvicorn (``sockets=[sock]``),
      so there's no free-port TOCTOU — the port can't be grabbed by another
      process in the window between "find a free port" and "uvicorn binds it".
    - ``ws="none"`` stops uvicorn from importing the deprecated ``websockets``
      legacy server classes. This is an SSE test with no websockets involved,
      so we skip that machinery entirely (and its DeprecationWarnings).

    A real server (rather than httpx.ASGITransport) is still required: the
    transport buffers the whole response before returning, which can't drive
    an interactive SSE stream — one where the client acts (posting an answer,
    or driving the progress hub) while the stream is still open.
    """
    config = uvicorn.Config(app, log_level="warning", lifespan="off", ws="none")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("uvicorn did not start in time")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        with contextlib.suppress(OSError):
            sock.close()

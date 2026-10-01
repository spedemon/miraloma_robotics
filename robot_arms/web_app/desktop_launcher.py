"""Native desktop entry point for the Mira robot controller."""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import webview

from app_paths import user_data_dir
from instance_lock import InstanceLock


def _verify_runtime() -> None:
    """Fail the build if a dependency needed by the packaged app is absent."""
    import bleak  # noqa: F401
    import esptool  # noqa: F401
    import flask  # noqa: F401
    import flask_socketio  # noqa: F401
    import serial  # noqa: F401


def _configure_file_logging() -> Path:
    log_path = user_data_dir() / "mira.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Windowed PyInstaller builds do not have stdout/stderr. Redirect legacy
    # print output so startup and serial diagnostics remain available.
    stream = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = stream
    sys.stderr = stream
    return log_path


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Mira's local server did not start: {last_error}")


def main() -> int:
    if "--verify-runtime" in sys.argv:
        _verify_runtime()
        return 0

    log_path = _configure_file_logging()
    instance_lock = InstanceLock()
    if not instance_lock.acquire():
        logging.info("Mira is already running; refusing to start a competing USB session.")
        return 0

    # Import after logging and writable paths are configured.
    import mira

    port = _available_port()
    url = f"http://127.0.0.1:{port}/"

    server_thread = threading.Thread(
        target=mira.run_server,
        kwargs={"host": "127.0.0.1", "port": port},
        name="mira-web-server",
        daemon=True,
    )
    server_thread.start()

    try:
        _wait_until_ready(url)
    except RuntimeError:
        logging.exception("Desktop startup failed; log file: %s", log_path)
        raise

    # Serial discovery happens after the UI server is available, allowing the
    # connection status to be shown immediately in the window.
    threading.Thread(
        target=mira.initialize_serial,
        name="mira-serial-discovery",
        daemon=True,
    ).start()

    window = webview.create_window(
        "Mira Robot Controller",
        url,
        width=1440,
        height=920,
        min_size=(960, 700),
        background_color="#f5f1e8",
    )

    def _on_closed() -> None:
        mira.shutdown_connections()

    window.events.closed += _on_closed
    webview.start(private_mode=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

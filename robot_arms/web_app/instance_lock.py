"""Cross-platform process lock preventing two Mira instances from sharing USB."""

from __future__ import annotations

import os
from pathlib import Path

from app_paths import user_data_dir


class InstanceLock:
    def __init__(self, path: Path | None = None):
        self.path = path or (user_data_dir() / "mira.lock")
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if not self.handle:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Mira is already running.")
        return self

    def __exit__(self, *_args):
        self.release()

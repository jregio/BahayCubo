"""
CuboCross Blueprint package.

Initializes pruning-table slots in background threads when the package
is first imported (i.e. when the Blueprint is registered).
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from .solver import (
    CROSS_PRUNING_DEPTH,
    XCROSS_PRUNING_DEPTH,
    CROSS_DEPTH_LIMIT,
    XCROSS_DEPTH_LIMIT,
    load_or_build_pruning_table,
)

_XCROSS_PAIRS = ("red_blue", "red_green", "orange_green", "orange_blue")

_ALL_KEYS = ["cross"] + [f"xcross_{p}" for p in _XCROSS_PAIRS]

_DEPTH_FOR = {
    "cross": CROSS_PRUNING_DEPTH,
    **{f"xcross_{p}": XCROSS_PRUNING_DEPTH for p in _XCROSS_PAIRS},
}

_DEPTH_LIMIT_FOR = {
    "cross": CROSS_DEPTH_LIMIT,
    **{f"xcross_{p}": XCROSS_DEPTH_LIMIT for p in _XCROSS_PAIRS},
}


class _TableSlot:
    def __init__(self, key: str):
        self.key = key
        self.table: Optional[Dict] = None
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.error: Optional[str] = None
        self._loading = False
        self._msg_lock = threading.Lock()
        self._messages: List[str] = []

    def _add_msg(self, msg: str) -> None:
        with self._msg_lock:
            self._messages.append(msg)

    def drain_messages(self) -> List[str]:
        with self._msg_lock:
            msgs = self._messages[:]
            self._messages.clear()
        return msgs

    def start_loading(self) -> None:
        with self.lock:
            if self.ready.is_set() or self._loading:
                return
            self._loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        key = self.key
        depth = _DEPTH_FOR[key]

        def progress_cb(msg: str) -> None:
            print(f"[{key}] {msg}", flush=True)
            self._add_msg(msg)

        try:
            print(f"[{key}] Starting table load (depth {depth})…", flush=True)
            t0 = time.time()
            self.table = load_or_build_pruning_table(key, depth, progress_cb=progress_cb)
            elapsed = time.time() - t0
            done_msg = f"Table ready — {len(self.table):,} states ({elapsed:.1f}s)"
            print(f"[{key}] {done_msg}", flush=True)
            self._add_msg(done_msg)
        except Exception as exc:
            self.error = str(exc)
            print(f"[{key}] ERROR: {exc}", flush=True)
        finally:
            self.ready.set()


_slots: Dict[str, _TableSlot] = {key: _TableSlot(key) for key in _ALL_KEYS}

for _slot in _slots.values():
    _slot.start_loading()

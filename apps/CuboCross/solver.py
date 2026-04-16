"""
Cross / XCross solver.

Design
------
State encoding
  We use *piece-based* encoding, not facelet-based encoding.
  Facelet-based encoding (recording colors at fixed positions) is incorrect
  because two full cube states can share the same mask encoding yet diverge
  after applying the same move (a move can pull a non-mask facelet into a
  mask position, and the two states may differ at that non-mask position).

  Piece-based encoding tracks the *position and orientation* of each relevant
  piece, which is closed under moves and unambiguous.

Cross encoding
  Track the 4 white edges (identified by their non-white color: B, R, G, O).
  For each: edge_slot (0-11) * 2 + orientation (0-1) → value in [0, 23].
  Encode as: v0 + 24*v1 + 24²*v2 + 24³*v3  (fits in a Python int).
  Total states: ≤ 24⁴ = 331,776 (actual reachable: 190,080).

XCross encoding
  Cross encoding  +  F2L edge (slot*2+ori, [0,23])  +  F2L corner (slot*3+ori, [0,23]).
  Encode as: cross_val * 576 + edge_val * 24 + corner_val.
  Total reachable: ~4.67M per pair (depth-7 BFS).

Pruning tables
  Built by BFS from the x2-solved state (Yellow=U, Blue=F).
  Cross: depth 8 — covers ALL cross states (God's number = 8).
  XCross: depth 7 — covers states ≤ 7 moves from solved; states not in table
          get heuristic value 8 (safe lower bound since table is complete
          through depth 7), guaranteeing optimality in IDA*.

  Tables are saved to binary files (tables/ directory) on first build and
  loaded from disk on subsequent runs.  Format: sorted (uint64 key, uint8
  value) pairs, 9 bytes each.

Solver
  IDA* with the pruning table as an admissible heuristic.
  Only pruning: no consecutive same-face moves (e.g. R then R' → use R2).
  Parallel-face sequences (e.g. U D U') are NOT pruned — they are valid
  optimal moves and pruning them would cause sub-optimal solutions.
"""

from __future__ import annotations

import os
import struct
import time
from collections import deque
from typing import Callable, Dict, List, Optional

from .cube import (
    CORNERS, EDGES, RUFLDB_MOVES,
    apply_move, apply_moves, solved_state,
)

# ── Constants ────────────────────────────────────────────────────────────────

CROSS_PRUNING_DEPTH: int = 8   # covers all cross states
CROSS_DEPTH_LIMIT:   int = 8

XCROSS_PRUNING_DEPTH: int = 7   # depth-7 table; IDA* searches up to limit
XCROSS_DEPTH_LIMIT:   int = 14  # xcross God's number ≈ 12-14

_TABLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tables")

# ── State encoders ────────────────────────────────────────────────────────────

def _encode_cross(state: List[str]) -> int:
    """
    Piece-based cross encoding.
    Tracks position + orientation of the 4 white edges (identified by their
    non-white color: B, R, G, O).
    """
    val = 0
    mult = 1
    for target in ('B', 'R', 'G', 'O'):
        for slot, (a, b) in enumerate(EDGES):
            ca, cb = state[a], state[b]
            if ca == 'W' and cb == target:
                val += mult * (slot * 2)
                break
            elif cb == 'W' and ca == target:
                val += mult * (slot * 2 + 1)
                break
        mult *= 24
    return val


def _encode_xcross(state: List[str], edge_colors: tuple, corner_colors: frozenset) -> int:
    """
    Piece-based xcross encoding.
    Cross encoding  +  F2L edge (slot*2+ori)  +  F2L corner (slot*3+ori).
    edge_colors: (color_a, color_b) — the two non-white colors of the F2L edge
                 in the order (first_facelet_color, second_facelet_color).
                 We search for either ordering.
    corner_colors: frozenset of 3 colors including 'W'.
    """
    cross_val = _encode_cross(state)

    # F2L edge
    ec0, ec1 = edge_colors
    edge_val = 0
    for slot, (a, b) in enumerate(EDGES):
        ca, cb = state[a], state[b]
        if ca == ec0 and cb == ec1:
            edge_val = slot * 2
            break
        elif ca == ec1 and cb == ec0:
            edge_val = slot * 2 + 1
            break

    # F2L corner
    corner_val = 0
    for slot, (a, b, c) in enumerate(CORNERS):
        if frozenset([state[a], state[b], state[c]]) == corner_colors:
            if state[a] == 'W':
                ori = 0
            elif state[b] == 'W':
                ori = 1
            else:
                ori = 2
            corner_val = slot * 3 + ori
            break

    return cross_val * 576 + edge_val * 24 + corner_val


# Build the four xcross encoder functions (one per pair)
_XCROSS_PAIR_PARAMS = {
    'red_blue':     (('R', 'B'), frozenset(['W', 'R', 'B'])),
    'orange_blue':  (('O', 'B'), frozenset(['W', 'O', 'B'])),
    'red_green':    (('R', 'G'), frozenset(['W', 'R', 'G'])),
    'orange_green': (('O', 'G'), frozenset(['W', 'O', 'G'])),
}

def _make_xcross_encoder(edge_colors, corner_colors):
    def encoder(state):
        return _encode_xcross(state, edge_colors, corner_colors)
    return encoder

_ENCODERS: Dict[str, Callable] = {
    'cross': _encode_cross,
    **{
        f'xcross_{pair}': _make_xcross_encoder(ec, cc)
        for pair, (ec, cc) in _XCROSS_PAIR_PARAMS.items()
    },
}

# ── Binary file I/O ───────────────────────────────────────────────────────────

def _table_path(key: str) -> str:
    os.makedirs(_TABLES_DIR, exist_ok=True)
    return os.path.join(_TABLES_DIR, f"{key}.bin")


def _save_table(table: Dict[int, int], path: str) -> None:
    items = sorted(table.items())
    with open(path, 'wb') as f:
        for key, val in items:
            f.write(struct.pack('>QB', key, val))


def _load_table(path: str) -> Dict[int, int]:
    table: Dict[int, int] = {}
    with open(path, 'rb') as f:
        data = f.read()
    for i in range(0, len(data), 9):
        key, val = struct.unpack_from('>QB', data, i)
        table[key] = val
    return table

# ── BFS table builder ─────────────────────────────────────────────────────────

def _build_table(
    encode_fn: Callable,
    max_depth: int,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[int, int]:
    """BFS from x2-solved state up to max_depth. Returns {enc: depth}."""
    start = apply_moves(solved_state(), ['x2'])
    start_enc = encode_fn(start)
    table: Dict[int, int] = {start_enc: 0}
    current_level = [(start, start_enc)]
    t0 = time.time()

    for depth in range(1, max_depth + 1):
        next_level = []
        for state, enc in current_level:
            for move in RUFLDB_MOVES:
                ns = apply_move(state, move)
                ne = encode_fn(ns)
                if ne not in table:
                    table[ne] = depth
                    next_level.append((ns, ne))

        elapsed = time.time() - t0
        msg = (f"Depth {depth}: {len(next_level):,} new states | "
               f"Total: {len(table):,} | {elapsed:.1f}s")
        if progress_cb:
            progress_cb(msg)

        if not next_level:
            break
        current_level = next_level

    return table


# ── Public API ────────────────────────────────────────────────────────────────

def load_or_build_pruning_table(
    key: str,
    depth: int,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[int, int]:
    """
    Load a pruning table from disk if it exists, otherwise build via BFS and save.

    key: one of 'cross', 'xcross_red_blue', 'xcross_orange_blue',
                'xcross_red_green', 'xcross_orange_green'
    depth: BFS depth (8 for cross, 7 for xcross)
    """
    path = _table_path(key)
    encode_fn = _ENCODERS[key]

    if os.path.exists(path):
        if progress_cb:
            progress_cb(f"Loading table from {path}…")
        t0 = time.time()
        table = _load_table(path)
        elapsed = time.time() - t0
        if progress_cb:
            progress_cb(f"Loaded {len(table):,} states in {elapsed:.1f}s")
        return table

    # Build from scratch
    if progress_cb:
        progress_cb(f"Building pruning table (depth {depth})…")
    table = _build_table(encode_fn, depth, progress_cb=progress_cb)

    if progress_cb:
        progress_cb(f"Saving table to {path}…")
    _save_table(table, path)
    if progress_cb:
        progress_cb(f"Saved {len(table):,} states")

    return table


def solve(
    state: List[str],
    key: str,
    table: Dict[int, int],
    depth_limit: int,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[List[str]]:
    """
    Find the shortest solution for `state` using IDA* with `table` as heuristic.

    key: table key (determines which encoder to use)
    table: pruning table from load_or_build_pruning_table
    depth_limit: maximum search depth
    status_cb: optional callback for progress messages

    Returns a list of moves (optimal solution), or None if not found.
    """
    encode_fn = _ENCODERS[key]
    pruning_depth = CROSS_PRUNING_DEPTH if key == 'cross' else XCROSS_PRUNING_DEPTH
    # States not in the table need more than pruning_depth moves → safe lower bound
    fallback_h = pruning_depth + 1

    goal_enc = encode_fn(apply_moves(solved_state(), ['x2']))
    start_enc = encode_fn(state)

    if start_enc == goal_enc:
        return []

    found: List[List[str]] = []

    def dfs(
        state: List[str],
        enc: int,
        g: int,
        bound: int,
        path: List[str],
        last_face: Optional[str],
    ) -> int:
        h = table.get(enc, fallback_h)
        f = g + h
        if f > bound:
            return f
        if enc == goal_enc:
            found.append(path[:])
            return -1  # signal: solution found

        t = bound + 1  # next bound candidate
        for move in RUFLDB_MOVES:
            # Prune: no consecutive same-face moves
            if move[0] == last_face:
                continue
            ns = apply_move(state, move)
            ne = encode_fn(ns)
            path.append(move)
            r = dfs(ns, ne, g + 1, bound, path, move[0])
            path.pop()
            if r == -1:
                return -1  # propagate solution found
            if r < t:
                t = r
        return t

    bound = table.get(start_enc, fallback_h)
    while bound <= depth_limit:
        if status_cb:
            status_cb(f"Searching depth {bound}…")
        r = dfs(state, start_enc, 0, bound, [], None)
        if r == -1:
            return found[0]
        if r > depth_limit:
            return None
        bound = r

    return None

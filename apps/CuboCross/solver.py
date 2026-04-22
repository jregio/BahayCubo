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

# ── Commute-equivalence canonicalisation ──────────────────────────────────────
#
# Two moves commute iff they act on **opposite faces of the same axis**.
# Standard axis groupings:
#   L/R   (x-axis)   canonical order: L before R
#   U/D   (y-axis)   canonical order: D before U
#   F/B   (z-axis)   canonical order: B before F
#
# To canonicalise a sequence: bubble-sort adjacent commuting pairs into the
# preferred order.  This collapses sequences that differ only in the ordering
# of non-conflicting opposite-face moves into one representative form.

_AXIS_OF: Dict[str, str] = {
    'R': 'x', 'L': 'x',
    'U': 'y', 'D': 'y',
    'F': 'z', 'B': 'z',
}

# Within each axis, the "first" face in canonical order
_AXIS_FIRST: Dict[str, str] = {'x': 'L', 'y': 'D', 'z': 'B'}


def _moves_commute(a: str, b: str) -> bool:
    """True iff moves a and b act on the same axis but different (opposite) faces."""
    fa, fb = a[0], b[0]
    if fa == fb:
        return False  # same face – never commute (and already pruned in search)
    return _AXIS_OF.get(fa) == _AXIS_OF.get(fb)


def _canonical_form(moves: List[str]) -> str:
    """
    Return the canonical representative of the commute-equivalence class of
    the move sequence.  Uses a single bubble-sort pass (repeated until stable).
    """
    seq = list(moves)
    changed = True
    while changed:
        changed = False
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            if not _moves_commute(a, b):
                continue
            # Both are on the same axis – put the canonical-first face earlier
            axis = _AXIS_OF[a[0]]
            first = _AXIS_FIRST[axis]
            # If a's face should come *after* b's face, swap
            if a[0] != first and b[0] == first:
                seq[i], seq[i + 1] = b, a
                changed = True
    return ' '.join(seq)

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
    max_solutions: int = 5,
    extra_depth: int = 2,
) -> Optional[List[dict]]:
    """
    Find up to max_solutions solutions for `state` using IDA*.

    Searches the optimal HTM first, collects solutions there, then continues
    at optimal+1 and optimal+2 (up to extra_depth beyond optimal) until
    max_solutions is reached or depth_limit + extra_depth is hit.

    Returns a list of dicts [{"htm": N, "solution": "R U ..."}] sorted by HTM,
    or None if no solution found at all.
    """
    encode_fn = _ENCODERS[key]
    pruning_depth = CROSS_PRUNING_DEPTH if key == 'cross' else XCROSS_PRUNING_DEPTH
    fallback_h = pruning_depth + 1

    goal_enc = encode_fn(apply_moves(solved_state(), ['x2']))
    start_enc = encode_fn(state)

    if start_enc == goal_enc:
        return [{"htm": 0, "solution": "(already solved)"}]

    all_found: List[dict] = []
    seen_canonical: set = set()   # deduplicate by commute-equivalence class
    optimal_htm: Optional[int] = None

    def dfs(
        cur_state: List[str],
        enc: int,
        g: int,
        bound: int,
        path: List[str],
        last_face: Optional[str],
        collecting: bool,      # True = gather all sols at this bound
        needed: int,           # stop when len(all_found) >= needed
    ) -> int:
        h = table.get(enc, fallback_h)
        f = g + h
        if f > bound:
            return f
        if enc == goal_enc:
            canon = _canonical_form(path)
            if canon in seen_canonical:
                if collecting:
                    return bound + 1
                return -1
            seen_canonical.add(canon)
            all_found.append({"htm": g, "solution": " ".join(path)})
            if len(all_found) >= needed:
                return -1  # enough solutions
            if collecting:
                return bound + 1  # keep searching at this depth
            return -1

        t = bound + 1
        for move in RUFLDB_MOVES:
            if move[0] == last_face:
                continue
            ns = apply_move(cur_state, move)
            ne = encode_fn(ns)
            path.append(move)
            r = dfs(ns, ne, g + 1, bound, path, move[0], collecting, needed)
            path.pop()
            if r == -1:
                return -1
            if r < t:
                t = r
        return t

    bound = table.get(start_enc, fallback_h)
    hard_limit = depth_limit + extra_depth

    while bound <= hard_limit and len(all_found) < max_solutions:
        if status_cb:
            status_cb(f"Searching depth {bound}…")

        # On first solve pass: collect up to max_solutions at optimal depth
        # On extra-depth passes: same collection logic
        collecting = True
        prev_count = len(all_found)
        r = dfs(state, start_enc, 0, bound, [], None, collecting, max_solutions)

        if len(all_found) > prev_count:
            # Found solutions at this depth
            if optimal_htm is None:
                optimal_htm = bound
            # If we reached max or exhausted this depth, try next depth for more
            if len(all_found) >= max_solutions:
                break
            if optimal_htm is not None and bound >= optimal_htm + extra_depth:
                break
        else:
            if r > hard_limit:
                break

        bound = bound + 1 if r == -1 else r

    return all_found if all_found else None

"""
CuboCross Blueprint — routes for the cross/xcross trainer.
Registered at url_prefix /cubocross.
"""

from __future__ import annotations

import json
import os
import random
import threading
from typing import Dict, Generator, List, Optional

from flask import Blueprint, Response, render_template, request, stream_with_context

from .cube import apply_moves, build_visualization_facelets, build_raw_facelets, solved_state
from .scrambler import generate_scramble, scramble_to_string
from .solver import solve
from . import _slots, _XCROSS_PAIRS, _DEPTH_LIMIT_FOR

# Cross-color pre-rotation mapping
_CROSS_COLOR_ROTATIONS: Dict[str, List[str]] = {
    "white":  [],
    "yellow": ["x2"],
    "orange": ["y'"],
    "red":    ["y"],
    "green":  ["x'"],
    "blue":   ["x"],
}

cubocross_bp = Blueprint(
    "cubocross",
    __name__,
    url_prefix="/cubocross",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _static_mtime_token(filename: str) -> str:
    """Integer mtime for cache-bust query (no manual ?v= bumps)."""
    try:
        return str(int(os.path.getmtime(os.path.join(_STATIC_DIR, filename))))
    except OSError:
        return "0"


@cubocross_bp.context_processor
def inject_static_cache_tokens() -> Dict:
    return {
        "static_v": {
            "css": _static_mtime_token("style.css"),
            "favicon": _static_mtime_token("favicon.svg"),
        },
    }


@cubocross_bp.after_request
def no_cache_static(response):
    if "/cubocross/static/" in request.path:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@cubocross_bp.route("/")
def index():
    return render_template("index.html")


@cubocross_bp.route("/api/status", methods=["GET"])
def api_status():
    """
    Stream table-loading progress as NDJSON.
    Yields status lines until all tables are ready, then a final 'ready' message.
    """

    def generate() -> Generator[str, None, None]:
        while True:
            all_ready = all(s.ready.is_set() for s in _slots.values())
            loaded = sum(1 for s in _slots.values() if s.ready.is_set())
            total = len(_slots)

            messages = []
            for key in _slots:
                for msg in _slots[key].drain_messages():
                    messages.append(f"[{key}] {msg}")

            for msg in messages:
                yield json.dumps({"type": "status", "message": msg, "loaded": loaded, "total": total}) + "\n"

            if all_ready:
                errors = {k: s.error for k, s in _slots.items() if s.error}
                if errors:
                    yield json.dumps({
                        "type": "error",
                        "error": "Failed to load: " + ", ".join(errors.keys()),
                    }) + "\n"
                else:
                    yield json.dumps({"type": "ready", "loaded": total, "total": total}) + "\n"
                return

            if not messages:
                yield json.dumps({
                    "type": "loading",
                    "message": f"Loading tables… ({loaded}/{total})",
                    "loaded": loaded,
                    "total": total,
                }) + "\n"

            threading.Event().wait(timeout=0.8)

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


def _generate_short_scramble(depth: int, cross_table: dict, pre_rotations: List[str]) -> List[str]:
    """
    Generate a scramble whose optimal cross solution is exactly `depth` moves.

    Strategy: randomly generate candidate scrambles, apply pre_rotations + x2,
    then look up the resulting cross state in the pruning table.  If the table
    says the cross distance equals `depth`, we have our scramble.

    The pruning table encodes distance to the x2-solved goal, so we apply
    the same pre_rotations + x2 suffix that the solver uses, then encode
    directly.  This is O(1) per candidate — typically found in < 50 tries.
    """
    from .scrambler import _ALL_MOVES, _is_valid_next
    from .solver import _encode_cross, CROSS_PRUNING_DEPTH
    from .cube import solved_state, apply_moves

    fallback_h = CROSS_PRUNING_DEPTH + 1

    for _ in range(2000):
        # Build a random WCA-constrained scramble of length between depth and depth+4
        scr_len = depth + random.randint(0, 4)
        moves: List[str] = []
        for _ in range(scr_len):
            last_face = moves[-1][0] if moves else None
            sec_last  = moves[-2][0] if len(moves) >= 2 else None
            valid = [m for m in _ALL_MOVES if _is_valid_next(m[0], last_face, sec_last)]
            moves.append(random.choice(valid))

        # Apply pre-rotation + x2 and encode the cross state
        state = apply_moves(solved_state(), pre_rotations + moves + ["x2"])
        enc = _encode_cross(state)
        dist = cross_table.get(enc, fallback_h)

        if dist == depth:
            return moves

    # Fallback: any scramble of the requested length
    moves = []
    for _ in range(depth + 2):
        last_face = moves[-1][0] if moves else None
        sec_last  = moves[-2][0] if len(moves) >= 2 else None
        valid = [m for m in _ALL_MOVES if _is_valid_next(m[0], last_face, sec_last)]
        moves.append(random.choice(valid))
    return moves


@cubocross_bp.route("/api/session", methods=["POST"])
def api_session():
    data = request.get_json(force=True, silent=True) or {}
    scramble_type  = data.get("scramble_type", "wca")   # "wca" | "shortlen" | "short" | "custom"
    short_depth    = int(data.get("short_depth", 5))
    shortlen_depth = max(5, min(20, int(data.get("shortlen_depth", 12))))
    custom_scramble = (data.get("custom_scramble") or "").strip()
    cross_color    = (data.get("cross_color") or "white").lower()

    pre_rotations = _CROSS_COLOR_ROTATIONS.get(cross_color, [])

    _VALID_MOVES = {
        "U", "U'", "U2", "D", "D'", "D2", "F", "F'", "F2", "B", "B'", "B2",
        "R", "R'", "R2", "L", "L'", "L2",
        "x", "x'", "x2", "y", "y'", "y2", "z", "z'", "z2",
        "M", "M'", "M2", "E", "E'", "E2", "S", "S'", "S2",
    }

    def generate() -> Generator[str, None, None]:

        not_ready = [k for k, s in _slots.items() if not s.ready.is_set()]
        if not_ready:
            yield json.dumps({
                "type": "status",
                "message": "Loading pruning tables, please wait…",
            }) + "\n"

        while True:
            still_waiting = [k for k, s in _slots.items() if not s.ready.is_set()]
            if not still_waiting:
                break
            for key in list(_slots.keys()):
                for msg in _slots[key].drain_messages():
                    yield json.dumps({"type": "status", "message": f"[{key}] {msg}"}) + "\n"
            threading.Event().wait(timeout=1.0)

        for key in _slots:
            for msg in _slots[key].drain_messages():
                yield json.dumps({"type": "status", "message": f"[{key}] {msg}"}) + "\n"

        errors = {k: s.error for k, s in _slots.items() if s.error}
        if errors:
            yield json.dumps({
                "type": "error",
                "error": "Failed to load tables: " + ", ".join(errors.keys()),
            }) + "\n"
            return

        yield json.dumps({"type": "status", "message": "Generating scramble…"}) + "\n"

        if scramble_type == "custom":
            parsed = [t for t in custom_scramble.split() if t in _VALID_MOVES]
            if not parsed and custom_scramble:
                yield json.dumps({
                    "type": "error",
                    "error": "Custom scramble contains no valid moves.",
                }) + "\n"
                return
            scramble_moves = parsed
            scramble_display_base = scramble_to_string(scramble_moves) if scramble_moves else "(empty)"
        elif scramble_type == "shortlen":
            # Plain WCA scramble of user-selected length (5-20 moves)
            scramble_moves = generate_scramble(shortlen_depth)
            scramble_display_base = scramble_to_string(scramble_moves)
        elif scramble_type == "short":
            # HTM: find a scramble whose optimal cross solution = depth moves
            depth = max(1, min(7, short_depth))
            scramble_moves = _generate_short_scramble(
                depth,
                _slots["cross"].table,
                pre_rotations,
            )
            scramble_display_base = scramble_to_string(scramble_moves)
        else:
            scramble_moves = generate_scramble(20)
            scramble_display_base = scramble_to_string(scramble_moves)

        # Apply pre-rotation for cross color, then scramble, then x2 (solver orientation)
        all_moves = pre_rotations + scramble_moves + ["x2"]
        scramble_display = scramble_display_base + " x2"
        scrambled_state = apply_moves(solved_state(), all_moves)

        yield json.dumps({"type": "status", "message": "Solving…"}) + "\n"

        solve_keys = ["cross"] + [f"xcross_{p}" for p in _XCROSS_PAIRS]
        results: Dict[str, Optional[List[str]]] = {}
        solve_errors: Dict[str, str] = {}

        solve_done = threading.Event()
        pending = [len(solve_keys)]
        lock = threading.Lock()

        def run_one(key: str) -> None:
            try:
                sol_list = solve(
                    scrambled_state, key, _slots[key].table,
                    _DEPTH_LIMIT_FOR[key],
                    max_solutions=5,
                    extra_depth=2,
                )
                with lock:
                    results[key] = sol_list
            except Exception as exc:
                with lock:
                    solve_errors[key] = str(exc)
            finally:
                with lock:
                    pending[0] -= 1
                    if pending[0] == 0:
                        solve_done.set()

        for key in solve_keys:
            threading.Thread(target=run_one, args=(key,), daemon=True).start()

        solve_done.wait()

        if solve_errors:
            yield json.dumps({
                "type": "error",
                "error": "Solver error: " + str(solve_errors),
            }) + "\n"
            return

        all_facelets = {
            "cross": build_visualization_facelets(scrambled_state, 'cross'),
        }
        for p in _XCROSS_PAIRS:
            all_facelets[p] = build_visualization_facelets(scrambled_state, 'xcross', p)

        result_map = {}
        for key in solve_keys:
            sol_list = results.get(key)
            short_key = key.replace("xcross_", "") if key != "cross" else "cross"
            if not sol_list:
                result_map[short_key] = {"htm": None, "solutions": []}
            else:
                # sol_list is List[{"htm": N, "solution": "..."}] sorted by htm
                sol_list_sorted = sorted(sol_list, key=lambda s: s["htm"])
                optimal_htm = sol_list_sorted[0]["htm"]
                result_map[short_key] = {
                    "htm": optimal_htm,
                    "solutions": sol_list_sorted,
                    # Legacy compat for history entries
                    "solution": sol_list_sorted[0]["solution"],
                }

        yield json.dumps({
            "type": "result",
            "scramble_display": scramble_display,
            "all_facelets": all_facelets,
            "raw_facelets": build_raw_facelets(scrambled_state),
            "results": result_map,
            "cross_color": cross_color,
        }) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


@cubocross_bp.route("/api/facelets", methods=["POST"])
def api_facelets():
    """Given a scramble string, return raw_facelets (no greying)."""
    data = request.get_json(force=True, silent=True) or {}
    scramble_str = (data.get("scramble") or "").strip()
    valid = {
        "U", "U'", "U2", "D", "D'", "D2", "F", "F'", "F2", "B", "B'", "B2",
        "R", "R'", "R2", "L", "L'", "L2",
        "x", "x'", "x2", "y", "y'", "y2", "z", "z'", "z2",
        "M", "M'", "M2", "E", "E'", "E2", "S", "S'", "S2",
    }
    moves = [t for t in scramble_str.split() if t in valid]
    state = apply_moves(solved_state(), moves)
    return {"raw_facelets": build_raw_facelets(state)}

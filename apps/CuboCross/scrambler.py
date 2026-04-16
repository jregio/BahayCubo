"""
WCA-style scramble generator.

Generates random-state-style scrambles using RUFLDB moves with the
standard constraints:
  - No two consecutive moves on the same face
  - No redundant parallel sequences (e.g. U D U is forbidden)
"""

from __future__ import annotations
import random
from typing import List

# Parallel face pairs
_PARALLEL = {
    'R': 'L', 'L': 'R',
    'U': 'D', 'D': 'U',
    'F': 'B', 'B': 'F',
}

_ALL_MOVES: List[str] = [
    'R', "R'", 'R2',
    'U', "U'", 'U2',
    'F', "F'", 'F2',
    'L', "L'", 'L2',
    'D', "D'", 'D2',
    'B', "B'", 'B2',
]


def generate_scramble(length: int = 20) -> List[str]:
    """Generate a WCA-style scramble of the given length."""
    moves: List[str] = []
    for _ in range(length):
        last_face = moves[-1][0] if moves else None
        second_last_face = moves[-2][0] if len(moves) >= 2 else None

        valid = [
            m for m in _ALL_MOVES
            if _is_valid_next(m[0], last_face, second_last_face)
        ]
        moves.append(random.choice(valid))
    return moves


def _is_valid_next(face: str, last_face: str | None, second_last_face: str | None) -> bool:
    """Return True if a move on `face` can follow the previous two faces."""
    if face == last_face:
        return False
    # Forbid redundant parallel: e.g. U D U — if last two are parallel,
    # don't repeat the second-last face
    if (second_last_face is not None
            and last_face is not None
            and _PARALLEL.get(last_face) == second_last_face
            and face == second_last_face):
        return False
    return True


def scramble_to_string(moves: List[str]) -> str:
    """Convert a list of moves to a space-separated string."""
    return ' '.join(moves)

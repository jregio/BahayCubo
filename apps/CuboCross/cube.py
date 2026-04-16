"""
Cube state engine for the cross/xcross trainer.

Facelet indexing (CrystalCube layout, 0-indexed):

              0  1  2
              3  4  5
              6  7  8
  9 10 11  12 13 14  15 16 17  18 19 20
 21 22 23  24 25 26  27 28 29  30 31 32
 33 34 35  36 37 38  39 40 41  42 43 44
             45 46 47
             48 49 50
             51 52 53

Face order: U(0-8), L(9-11,21-23,33-35), F(12-14,24-26,36-38),
            R(15-17,27-29,39-41), B(18-20,30-32,42-44), D(45-53)

B face is mirrored when unfolded:
  B[0]=18=UBR, B[2]=20=UBL, B[6]=42=DBR, B[8]=44=DBL

D face layout:
  D[0]=45=DFL, D[2]=47=DFR, D[6]=51=DBL, D[8]=53=DBR

WCA solved orientation: White=U, Orange=L, Green=F, Red=R, Blue=B, Yellow=D
"""

from __future__ import annotations
from typing import List, Optional, Tuple

# ── Color constants ──────────────────────────────────────────────────────────
W, O, G, R, B, Y = 'W', 'O', 'G', 'R', 'B', 'Y'

COLOR_HEX = {
    W: '#ffffff',
    Y: '#ffd700',
    R: '#c62828',
    O: '#ef6c00',
    G: '#2e7d32',
    B: '#1565c0',
}
GREY_HEX = '#555555'

# ── Solved state (WCA: White=U, Green=F) ────────────────────────────────────
def solved_state() -> List[str]:
    return [
        W,W,W, W,W,W, W,W,W,           # U: 0-8
        O,O,O, G,G,G, R,R,R, B,B,B,    # row 1: 9-20
        O,O,O, G,G,G, R,R,R, B,B,B,    # row 2: 21-32
        O,O,O, G,G,G, R,R,R, B,B,B,    # row 3: 33-44
        Y,Y,Y, Y,Y,Y, Y,Y,Y,           # D: 45-53
    ]

# ── Move permutations (from CrystalCube moves.ts) ───────────────────────────
# Each entry is a list of [from, to] pairs: sticker at 'from' moves to 'to'.
_FACE_PERMS_RAW = {
    'R': [[2,42],[5,30],[8,18],[14,2],[15,17],[16,29],[17,41],[18,53],[26,5],[27,16],[29,40],[30,50],[38,8],[39,15],[40,27],[41,39],[42,47],[47,14],[50,26],[53,38]],
    'L': [[0,12],[3,24],[6,36],[9,11],[10,23],[11,35],[12,45],[20,6],[21,10],[23,34],[24,48],[32,3],[33,9],[34,21],[35,33],[36,51],[44,0],[45,44],[48,32],[51,20]],
    'U': [[0,2],[1,5],[2,8],[3,1],[5,7],[6,0],[7,3],[8,6],[9,18],[10,19],[11,20],[12,9],[13,10],[14,11],[15,12],[16,13],[17,14],[18,15],[19,16],[20,17]],
    'D': [[33,36],[34,37],[35,38],[36,39],[37,40],[38,41],[39,42],[40,43],[41,44],[42,33],[43,34],[44,35],[45,47],[46,50],[47,53],[48,46],[50,52],[51,45],[52,48],[53,51]],
    'F': [[6,15],[7,27],[8,39],[11,8],[12,14],[13,26],[14,38],[15,47],[23,7],[24,13],[26,37],[27,46],[35,6],[36,12],[37,24],[38,36],[39,45],[45,11],[46,23],[47,35]],
    'B': [[0,33],[1,21],[2,9],[9,51],[17,0],[18,20],[19,32],[20,44],[21,52],[29,1],[30,19],[32,43],[33,53],[41,2],[42,18],[43,30],[44,42],[51,41],[52,29],[53,17]],
    'M': [[1,13],[4,25],[7,37],[13,46],[19,7],[25,49],[31,4],[37,52],[43,1],[46,43],[49,31],[52,19]],
    'E': [[21,24],[22,25],[23,26],[24,27],[25,28],[26,29],[27,30],[28,31],[29,32],[30,21],[31,22],[32,23]],
    'S': [[3,16],[4,28],[5,40],[10,5],[16,50],[22,4],[28,49],[34,3],[40,48],[48,10],[49,22],[50,34]],
}

def _invert_perm(perm: list) -> list:
    return [[b, a] for a, b in perm]

def _compose_perms(*perms) -> list:
    """Compose multiple [from,to] permutations into one."""
    combined = list(range(54))
    for perm in perms:
        f = list(range(54))
        for a, b in perm:
            f[a] = b
        combined = [f[combined[i]] for i in range(54)]
    return [[i, combined[i]] for i in range(54) if combined[i] != i]

def _double_perm(perm: list) -> list:
    """Apply a permutation twice."""
    f = list(range(54))
    for a, b in perm:
        f[a] = b
    f2 = [f[f[i]] for i in range(54)]
    return [[i, f2[i]] for i in range(54) if f2[i] != i]

# Build rotation perms: x = R + inv(M) + inv(L), y = U + inv(E) + inv(D), z = F + S + inv(B)
_x_raw = _compose_perms(_FACE_PERMS_RAW['R'], _invert_perm(_FACE_PERMS_RAW['M']), _invert_perm(_FACE_PERMS_RAW['L']))
_y_raw = _compose_perms(_FACE_PERMS_RAW['U'], _invert_perm(_FACE_PERMS_RAW['E']), _invert_perm(_FACE_PERMS_RAW['D']))
_z_raw = _compose_perms(_FACE_PERMS_RAW['F'], _FACE_PERMS_RAW['S'], _invert_perm(_FACE_PERMS_RAW['B']))

_ROT_PERMS_RAW = {'x': _x_raw, 'y': _y_raw, 'z': _z_raw}

def _build_all_move_perms() -> dict:
    """Build the full move permutation table including ', 2 variants."""
    all_perms = {}
    for name, raw in {**_FACE_PERMS_RAW, **_ROT_PERMS_RAW}.items():
        if name in ('M', 'E', 'S'):
            continue  # internal only; not exposed as user moves
        all_perms[name] = raw
        all_perms[name + "'"] = _invert_perm(raw)
        all_perms[name + '2'] = _double_perm(raw)
    return all_perms

MOVE_PERMS: dict = _build_all_move_perms()

# RUFLDB move set (for solver and scrambler)
RUFLDB_MOVES: List[str] = [
    'R', "R'", 'R2',
    'U', "U'", 'U2',
    'F', "F'", 'F2',
    'L', "L'", 'L2',
    'D', "D'", 'D2',
    'B', "B'", 'B2',
]

# ── State manipulation ───────────────────────────────────────────────────────

def apply_move(state: List[str], move: str) -> List[str]:
    """Apply a single move to a cube state. Returns a new state."""
    perm = MOVE_PERMS[move]
    new_state = state[:]
    for a, b in perm:
        new_state[b] = state[a]
    return new_state

def apply_moves(state: List[str], moves: List[str]) -> List[str]:
    """Apply a sequence of moves to a cube state. Returns a new state."""
    for m in moves:
        state = apply_move(state, m)
    return state

# ── Piece geometry ───────────────────────────────────────────────────────────

# 12 edge pairs: (facelet_a, facelet_b)
EDGES: List[Tuple[int, int]] = [
    (7,  13),   # UF
    (5,  16),   # UR
    (1,  19),   # UB
    (3,  10),   # UL
    (26, 27),   # FR
    (24, 23),   # FL
    (30, 29),   # BR
    (32, 21),   # BL
    (46, 37),   # DF
    (50, 40),   # DR
    (52, 43),   # DB
    (48, 34),   # DL
]

# 8 corner triples: (U/D-sticker, F/B-sticker, R/L-sticker)
CORNERS: List[Tuple[int, int, int]] = [
    (8,  14, 15),   # UFR
    (6,  12, 11),   # UFL
    (2,  18, 17),   # UBR
    (0,  20,  9),   # UBL
    (47, 38, 39),   # DFR
    (45, 36, 35),   # DFL
    (53, 42, 41),   # DBR
    (51, 44, 33),   # DBL
]

# Center facelets (U, L, F, R, B, D)
CENTERS: List[int] = [4, 22, 25, 28, 31, 49]

# XCross pair definitions: colors of the F2L edge and corner (in x2 orientation)
# x2 orientation: Yellow=U, White=D, Blue=F, Green=B, Red=R, Orange=L
_XCROSS_PAIRS = {
    'red_blue':     {'edge': frozenset([R, B]), 'corner': frozenset([W, R, B])},
    'orange_blue':  {'edge': frozenset([O, B]), 'corner': frozenset([W, O, B])},
    'red_green':    {'edge': frozenset([R, G]), 'corner': frozenset([W, R, G])},
    'orange_green': {'edge': frozenset([O, G]), 'corner': frozenset([W, O, G])},
}

# Mask indices for the solver (positions of relevant pieces in the x2-solved state).
# In x2-solved state: Yellow=U, White=D, Blue=F, Green=B, Red=R, Orange=L.
# Cross mask: 6 centers + 4 white edge pairs (white edges are at DF/DR/DB/DL in x2-solved).
_CROSS_MASK: List[int] = sorted(
    CENTERS + [46, 37, 50, 40, 52, 43, 48, 34]
)

# XCross masks: cross mask + F2L edge pair + F2L corner triple (solved positions)
_XCROSS_MASKS: dict = {
    'red_blue':     sorted(_CROSS_MASK + [26, 27, 47, 38, 39]),   # FR edge + DFR corner
    'orange_blue':  sorted(_CROSS_MASK + [24, 23, 45, 36, 35]),   # FL edge + DFL corner
    'red_green':    sorted(_CROSS_MASK + [30, 29, 53, 42, 41]),   # BR edge + DBR corner
    'orange_green': sorted(_CROSS_MASK + [32, 21, 51, 44, 33]),   # BL edge + DBL corner
}

def get_mask_indices(mode: str, pair: Optional[str] = None) -> List[int]:
    """Return the list of facelet indices that define the goal for the solver."""
    if mode == 'cross':
        return _CROSS_MASK
    return _XCROSS_MASKS[pair]

# ── Encoding for pruning table ───────────────────────────────────────────────

def apply_mask(state: List[str], mask_indices: List[int]) -> List[str]:
    """Return a state with only the masked positions filled (others as '_')."""
    result = ['_'] * 54
    for i in mask_indices:
        result[i] = state[i]
    return result

def encode(masked_state: List[str]) -> tuple:
    """Encode a masked state as a hashable tuple (only non-'_' positions)."""
    return tuple(masked_state[i] for i in range(54) if masked_state[i] != '_')

# ── Visualization ────────────────────────────────────────────────────────────

# The frontend reads facelets[display_idx] for each visual position, where
# display_idx comes from the FACE_MAP in index.html.  For faces rendered with
# a CSS mirror (B: rotateY(180°), L: rotateY(-90°), D: rotateX(-90°)) the
# FACE_MAP already reverses the row order so the 3D stickers land in the right
# physical spots.  However, because backface-visibility is visible, the user
# sees the B face un-flipped (grid order), so what appears at visual position i
# is facelets[FACE_MAP[i]] — not the CSS-flipped version.
#
# Net-map order (how we index the cube internally):
#   B: [18,19,20, 30,31,32, 42,43,44]   L: [9,10,11, 21,22,23, 33,34,35]
#   D: [45,46,47, 48,49,50, 51,52,53]
#
# FACE_MAP order (what the frontend reads per visual slot):
#   B: [20,19,18, 32,31,30, 44,43,42]   L: [11,10,9, 23,22,21, 35,34,33]
#   D: [47,46,45, 50,49,48, 53,52,51]
#
# Mapping: display_slot i on face F reads facelets[FACE_MAP[F][i]].
# We want the color of cube index NET_MAP[F][i] to appear at that slot.
# So: facelets[FACE_MAP[F][i]] must hold the color of NET_MAP[F][i].
# Build a lookup: display_index -> cube_index.

_DISPLAY_TO_CUBE: List[int] = list(range(54))  # identity for U, F, R
for _net, _disp in [
    # B face
    ([18,19,20, 30,31,32, 42,43,44], [20,19,18, 32,31,30, 44,43,42]),
    # L face
    ([9,10,11, 21,22,23, 33,34,35],  [11,10,9,  23,22,21, 35,34,33]),
    # D face
    ([45,46,47, 48,49,50, 51,52,53], [47,46,45, 50,49,48, 53,52,51]),
]:
    for cube_idx, disp_idx in zip(_net, _disp):
        _DISPLAY_TO_CUBE[disp_idx] = cube_idx


def build_raw_facelets(state: List[str]) -> List[dict]:
    """All 54 facelets with real colors, no greying. Uses same display-slot
    mapping as build_visualization_facelets so the frontend can use FACE_MAP."""
    return [{'bg': COLOR_HEX[state[_DISPLAY_TO_CUBE[i]]]} for i in range(54)]


def build_visualization_facelets(state: List[str], mode: str, pair: Optional[str] = None) -> List[dict]:
    """
    Build the 54-element facelets array for the frontend.
    Relevant pieces are colored; all others are grey.

    The output is indexed by *display slot* (what the frontend's FACE_MAP
    reads), not by raw cube index.  This accounts for the left-right mirror
    applied to the B, L, and D faces by the CSS 3D transforms.

    Cross mode:  6 centers + 4 white edge pieces (8 facelets) = 14 total
    XCross mode: cross facelets + F2L edge (2) + F2L corner (3) = 19 total
    """
    # Collect the cube indices of relevant pieces
    relevant: set = set(CENTERS)

    for (a, b) in EDGES:
        if state[a] == W or state[b] == W:
            relevant.add(a)
            relevant.add(b)

    if mode == 'xcross' and pair in _XCROSS_PAIRS:
        pair_info = _XCROSS_PAIRS[pair]
        edge_colors = pair_info['edge']
        corner_colors = pair_info['corner']

        for (a, b) in EDGES:
            if frozenset([state[a], state[b]]) == edge_colors:
                relevant.add(a)
                relevant.add(b)
                break

        for (a, b, c) in CORNERS:
            if frozenset([state[a], state[b], state[c]]) == corner_colors:
                relevant.add(a)
                relevant.add(b)
                relevant.add(c)
                break

    # Build output indexed by display slot.
    # For each display slot i, _DISPLAY_TO_CUBE[i] gives the cube index whose
    # color should appear there.
    result = []
    for disp_idx in range(54):
        cube_idx = _DISPLAY_TO_CUBE[disp_idx]
        if cube_idx in relevant:
            result.append({'bg': COLOR_HEX[state[cube_idx]]})
        else:
            result.append({'bg': GREY_HEX})
    return result

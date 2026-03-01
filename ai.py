"""
ai.py — Fancy Chess AI  v6  (production)
==========================================
Improvements over v5:
  - 25 named openings with deeper lines (Ruy Lopez, Sicilian, KID, Nimzo, Catalan, etc.)
  - Smarter eval: passed pawns, rook on open files, rook on 7th, bishop pair,
    pawn shelter for king, mobility per piece type, centre control
  - Faster mate-in-N: dedicated alpha-beta with mate window, early-exit per ply,
    checks/captures ordered first, no slow quick_eval at leaf during mate search
  - Null-move pruning in main search (depth >= 3)
  - History heuristic for quiet move ordering
  - Larger TT (1M entries), flag-aware probing
  - ELO tiers tuned for responsiveness
"""

import time, random, logging
from logic import Board, MoveGenerator

log = logging.getLogger("fancy_chess.ai")
print("[ai] Module loaded — Fancy Chess AI v6")

GEN = MoveGenerator()

# ─────────────────────────────────────────────────────────────────────────────
# Opening book — 25 named lines
# Each line is a flat list: (from_row, from_col), (to_row, to_col), ...
# White moves are at even indices; black at odd indices.
# ─────────────────────────────────────────────────────────────────────────────
_BOOK_LINES = {
    "Ruy Lopez":
        [(1,4),(3,4),(6,4),(4,4),(0,6),(2,5),(7,1),(5,2),(0,5),(3,2),
         (4,4),(3,4),(0,3),(4,7),(3,4),(4,4),(0,1),(2,2)],
    "Italian Game":
        [(1,4),(3,4),(6,4),(4,4),(0,6),(2,5),(7,1),(5,2),(0,5),(3,2),
         (7,5),(6,4),(0,3),(2,3),(0,1),(2,2)],
    "Scotch Game":
        [(1,4),(3,4),(6,4),(4,4),(0,6),(2,5),(1,3),(3,3),(3,4),(4,4),
         (0,5),(3,2),(0,1),(2,2)],
    "King's Gambit":
        [(1,4),(3,4),(6,4),(4,4),(1,5),(3,5),(0,5),(2,2),(6,3),(5,3),
         (0,6),(2,5)],
    "Petrov Defense":
        [(1,4),(3,4),(6,4),(4,4),(0,6),(2,5),(7,6),(5,5),(2,5),(4,4),
         (0,3),(2,3),(3,4),(1,3)],
    "Four Knights":
        [(1,4),(3,4),(6,4),(4,4),(0,6),(2,5),(7,6),(5,5),(0,1),(2,2),
         (7,1),(5,2)],
    "Vienna Game":
        [(1,4),(3,4),(6,4),(4,4),(0,1),(2,2),(0,6),(2,5),(7,5),(6,4)],

    # Sicilian
    "Sicilian Najdorf":
        [(1,4),(3,4),(6,2),(4,2),(0,6),(2,5),(6,3),(4,3),(0,3),(3,3),
         (7,1),(5,2),(0,5),(3,2)],
    "Sicilian Dragon":
        [(1,4),(3,4),(6,2),(4,2),(0,6),(2,5),(6,6),(5,6),(1,3),(3,3),
         (0,1),(2,2),(0,5),(2,3)],
    "Sicilian Scheveningen":
        [(1,4),(3,4),(6,2),(4,2),(0,6),(2,5),(6,4),(5,4),(1,3),(3,3),
         (7,1),(5,2),(0,5),(3,2)],
    "Sicilian Kan":
        [(1,4),(3,4),(6,2),(4,2),(0,6),(2,5),(6,4),(5,4),(1,3),(3,3),
         (7,6),(5,5)],
    "Sicilian Classical":
        [(1,4),(3,4),(6,2),(4,2),(0,6),(2,5),(6,1),(5,2),(1,3),(3,3),
         (7,5),(6,6)],

    # Semi-open
    "French Defense":
        [(1,4),(3,4),(6,4),(5,4),(1,3),(3,3),(7,1),(5,2),(6,3),(5,3),
         (0,2),(2,4)],
    "French Advance":
        [(1,4),(3,4),(6,4),(5,4),(1,3),(3,3),(5,4),(4,4),(0,2),(2,4),
         (6,3),(5,3),(0,6),(2,5)],
    "Caro-Kann":
        [(1,4),(3,4),(6,2),(5,2),(1,3),(3,3),(5,2),(4,3),(0,6),(2,5),
         (6,3),(5,3)],
    "Scandinavian":
        [(1,4),(3,4),(6,3),(4,3),(3,4),(4,3),(7,3),(4,3),(0,6),(2,5),
         (7,1),(5,2)],
    "Pirc Defense":
        [(1,4),(3,4),(6,3),(5,3),(1,3),(3,3),(6,6),(5,6),(0,1),(2,2),
         (7,5),(6,6)],

    # Closed / d4
    "QGD":
        [(1,3),(3,3),(6,3),(4,3),(1,2),(3,2),(0,1),(2,2),(7,6),(5,5),
         (0,2),(1,3),(0,3),(1,4)],
    "QGA":
        [(1,3),(3,3),(6,3),(4,3),(1,2),(3,2),(4,3),(3,2),(0,6),(2,5),
         (7,6),(5,5)],
    "King's Indian":
        [(1,3),(3,3),(6,6),(5,6),(1,2),(3,2),(7,5),(6,6),(0,1),(2,2),
         (6,3),(4,3),(1,4),(3,4),(7,1),(5,2)],
    "Nimzo-Indian":
        [(1,3),(3,3),(6,6),(5,6),(1,2),(3,2),(7,5),(6,6),(0,6),(2,5),
         (6,1),(5,2),(0,2),(2,4),(7,5),(5,3)],
    "Grunfeld":
        [(1,3),(3,3),(6,6),(5,6),(1,2),(3,2),(6,3),(4,3),(0,6),(2,5),
         (7,5),(6,6),(1,4),(3,4),(4,3),(3,4)],
    "Catalan":
        [(1,3),(3,3),(6,6),(5,6),(1,2),(3,2),(6,3),(5,3),(0,6),(2,5),
         (7,5),(6,6),(0,2),(1,3)],
    "Dutch Defense":
        [(1,3),(3,3),(6,5),(5,5),(1,2),(3,2),(6,6),(5,6),(0,2),(1,3)],

    # Flank
    "London System":
        [(1,3),(3,3),(0,6),(2,5),(7,6),(5,5),(0,2),(1,3),(1,4),(2,4),
         (7,5),(6,6),(0,1),(2,2)],
    "English Opening":
        [(1,2),(3,2),(6,4),(4,4),(0,6),(2,5),(7,6),(5,5),(0,1),(2,2),
         (7,1),(5,2),(1,3),(3,3)],
    "Reti Opening":
        [(0,6),(2,5),(6,3),(4,3),(1,2),(3,2),(6,4),(5,4),(1,6),(2,6),
         (7,6),(5,5),(0,5),(1,6)],
    "Bird's Opening":
        [(1,5),(3,5),(6,4),(4,4),(0,6),(2,5),(7,6),(5,5),(1,4),(3,4),
         (0,2),(2,4)],
}

_BOOK: dict = {}
_BOOK_READY = False


def _build_book():
    global _BOOK, _BOOK_READY
    if _BOOK_READY:
        return
    from logic import Piece, build_default_pieces
    pt = build_default_pieces()
    order = ["Rook","Knight","Bishop","Queen","King","Bishop","Knight","Rook"]
    built = 0
    for opening_name, line in _BOOK_LINES.items():
        b = Board(8, 8)
        for c, pname in enumerate(order):
            if pname in pt:
                b.place(Piece(pt[pname], 0, 0, c))
                b.place(Piece(pt[pname], 1, 7, c))
        for c in range(8):
            b.place(Piece(pt["Pawn"], 0, 1, c))
            b.place(Piece(pt["Pawn"], 1, 6, c))
        for i in range(0, len(line) - 1, 2):
            fp, tp = line[i], line[i + 1]
            key = b.position_key()
            _BOOK.setdefault(key, []).append((fp, tp))
            moves = GEN.all_moves(b, b.current_player, legal_only=True)
            mv = next((m for m in moves
                       if m["from_pos"] == fp and m["to_pos"] == tp), None)
            if mv is None:
                break
            b = b.apply_move(mv)
            built += 1
    _BOOK_READY = True
    print(f"[ai] Opening book ready: {len(_BOOK)} positions, {built} half-moves, "
          f"{len(_BOOK_LINES)} openings")


def book_move(board):
    """Return a book move for the current position, or None."""
    _build_book()
    key = board.position_key()
    candidates = _BOOK.get(key)
    if not candidates:
        return None
    fp, tp = random.choice(candidates)
    moves = GEN.all_moves(board, board.current_player, legal_only=True)
    mv = next((m for m in moves
               if m["from_pos"] == fp and m["to_pos"] == tp), None)
    if mv:
        print(f"[ai] Book: {fp}->{tp}")
    return mv


# ─────────────────────────────────────────────────────────────────────────────
# ELO levels
# ─────────────────────────────────────────────────────────────────────────────
ELO_LEVELS = [
    {"name": "Beginner",     "elo":  800, "depth": 1, "noise": 220, "blunder": 0.40, "time": 0.4,  "book": False},
    {"name": "Casual",       "elo": 1000, "depth": 1, "noise":  75, "blunder": 0.18, "time": 0.6,  "book": False},
    {"name": "Club",         "elo": 1200, "depth": 2, "noise":  30, "blunder": 0.06, "time": 1.2,  "book": True},
    {"name": "Intermediate", "elo": 1400, "depth": 3, "noise":  10, "blunder": 0.02, "time": 2.5,  "book": True},
    {"name": "Advanced",     "elo": 1800, "depth": 4, "noise":   2, "blunder": 0.00, "time": 5.0,  "book": True},
    {"name": "Master",       "elo": 2200, "depth": 5, "noise":   0, "blunder": 0.00, "time": 10.0, "book": True},
]

# ─────────────────────────────────────────────────────────────────────────────
# Piece values + piece-square tables
# ─────────────────────────────────────────────────────────────────────────────
_MATERIAL = {"King": 20000, "Queen": 950, "Rook": 510,
             "Bishop": 340, "Knight": 325, "Pawn": 100}


def _pval(pt) -> int:
    """Centipawn value: explicit .value field first, then name lookup, then lethality estimate."""
    if pt.value > 0:
        return pt.value
    return _MATERIAL.get(pt.name, max(50, int(pt.lethality * 200)))


def _mirror(t):
    return list(reversed(t))


# White PSTs (row 0 = rank 1 = white back rank)
_PST_PAWN = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 27, 27, 10,  5,  5,
     0,  0,  0, 22, 22,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
_PST_KNIGHT = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]
_PST_BISHOP = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]
_PST_ROOK = [
     0,  0,  0,  5,  5,  0,  0,  0,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     5, 12, 12, 12, 12, 12, 12,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
_PST_QUEEN = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]
_PST_KING_MG = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]
_PST_KING_EG = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]

_PST_W = {
    "Pawn": _PST_PAWN, "Knight": _PST_KNIGHT, "Bishop": _PST_BISHOP,
    "Rook": _PST_ROOK, "Queen": _PST_QUEEN, "King": _PST_KING_MG,
}
_PST_B = {k: _mirror(v) for k, v in _PST_W.items()}
_PST_KING_EG_B = _mirror(_PST_KING_EG)


def _pst(piece, endgame: bool) -> int:
    name = piece.piece_type.name
    if name == "King":
        tbl = (_PST_KING_EG if piece.owner == 0 else _PST_KING_EG_B) if endgame \
              else (_PST_KING_MG if piece.owner == 0 else _mirror(_PST_KING_MG))
    elif piece.owner == 0:
        tbl = _PST_W.get(name)
    else:
        tbl = _PST_B.get(name)
    if tbl is None:
        return 0
    idx = piece.row * 8 + piece.col
    return tbl[idx] if 0 <= idx < 64 else 0


def _is_endgame(board) -> bool:
    queens = sum(1 for p in board.all_pieces() if p.piece_type.name == "Queen")
    minors = sum(1 for p in board.all_pieces()
                 if p.piece_type.name in ("Bishop", "Knight", "Rook"))
    return queens == 0 or (queens <= 2 and minors <= 2)


# ─────────────────────────────────────────────────────────────────────────────
# Positional evaluation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pawn_structure(board) -> int:
    score = 0
    for owner in (0, 1):
        sign = 1 if owner == 0 else -1
        pawns     = [p for p in board.all_pieces(owner)     if p.piece_type.name == "Pawn"]
        opp_pawns = [p for p in board.all_pieces(1 - owner) if p.piece_type.name == "Pawn"]
        my_cols   = [p.col for p in pawns]
        opp_cols  = {p.col for p in opp_pawns}
        for p in pawns:
            c = p.col
            # Doubled pawn
            if my_cols.count(c) > 1:
                score -= sign * 22
            # Isolated pawn
            if (c - 1) not in my_cols and (c + 1) not in my_cols:
                score -= sign * 18
            # Passed pawn — no opposing pawn on same or adjacent files ahead
            if c not in opp_cols and (c-1) not in opp_cols and (c+1) not in opp_cols:
                adv = p.row if owner == 0 else (7 - p.row)
                score += sign * (12 + adv * 9)   # more bonus the further advanced
    return score


def _rook_bonuses(board) -> int:
    """Rook on open/semi-open file and rook on 7th rank bonuses."""
    score = 0
    for owner in (0, 1):
        sign      = 1 if owner == 0 else -1
        my_pawns  = {p.col for p in board.all_pieces(owner)     if p.piece_type.name == "Pawn"}
        opp_pawns = {p.col for p in board.all_pieces(1 - owner) if p.piece_type.name == "Pawn"}
        seventh   = 6 if owner == 0 else 1          # 7th rank for this owner
        for p in board.all_pieces(owner):
            if p.piece_type.name != "Rook":
                continue
            c = p.col
            if c not in my_pawns and c not in opp_pawns:
                score += sign * 25   # fully open file
            elif c not in my_pawns:
                score += sign * 12   # semi-open file
            if p.row == seventh:
                score += sign * 18   # rook on 7th


    return score


def _king_safety(board, eg: bool) -> int:
    if eg:
        return 0
    score = 0
    for owner in (0, 1):
        king = board.find_king(owner)
        if not king:
            continue
        sign       = 1 if owner == 0 else -1
        shield_row = king.row + (1 if owner == 0 else -1)
        shields    = 0
        for dc in (-1, 0, 1):
            c = king.col + dc
            if 0 <= c < 8:
                p = board.get(shield_row, c)
                if p and p.piece_type.symbol in ("P", "p") and p.owner == owner:
                    shields += 1
                # Open file next to king is dangerous
                elif not any(q.col == c and q.piece_type.name == "Pawn"
                             for q in board.all_pieces()):
                    score -= sign * 10
        score += sign * (shields * 16 - 8)
    return score


def _centre_control(board) -> int:
    """Bonus for pieces controlling d4,d5,e4,e5 (rows 3-4, cols 3-4)."""
    centre = {(3, 3), (3, 4), (4, 3), (4, 4)}
    score  = 0
    for p in board.all_pieces():
        sign = 1 if p.owner == 0 else -1
        if (p.row, p.col) in centre:
            score += sign * 8
    return score


def _development(board) -> int:
    if len(board.move_history) > 16:
        return 0
    score = 0
    for p in board.all_pieces():
        sign = 1 if p.owner == 0 else -1
        back = 0 if p.owner == 0 else 7
        if p.piece_type.name in ("Knight", "Bishop") and p.row != back:
            score += sign * 12
        if p.piece_type.name == "Queen" and p.has_moved and len(board.move_history) < 10:
            score -= sign * 18
    return score


def quick_eval(board, perspective: int = 0) -> int:
    """
    Full positional evaluation.
    perspective=0 → absolute (positive = white ahead)
    perspective=1 → relative to black (negated)
    """
    result = GEN.game_result(board)
    if result == "checkmate":
        loser = board.current_player
        raw   = -95000 if loser == 0 else 95000
        return raw if perspective == 0 else -raw
    if result in ("stalemate", "50move", "repetition", "material"):
        return 0

    eg    = _is_endgame(board)
    score = 0

    # Material + PST
    for p in board.all_pieces():
        v = _pval(p.piece_type) + _pst(p, endgame=eg)
        score += v if p.owner == 0 else -v

    # Bishop pair
    for owner in (0, 1):
        if sum(1 for p in board.all_pieces(owner) if p.piece_type.name == "Bishop") >= 2:
            score += 28 if owner == 0 else -28

    # Mobility (lightweight: just move count × weight)
    _mob_w = {"Queen": 2, "Rook": 3, "Bishop": 4, "Knight": 4}
    for p in board.all_pieces():
        w = _mob_w.get(p.piece_type.name, 0)
        if w:
            mob = len(GEN.get_moves(p, board, legal_only=False)) * w
            score += mob if p.owner == 0 else -mob

    try: score += _pawn_structure(board)
    except Exception: pass
    try: score += _rook_bonuses(board)
    except Exception: pass
    try: score += _king_safety(board, eg)
    except Exception: pass
    try: score += _centre_control(board)
    except Exception: pass
    try: score += _development(board)
    except Exception: pass

    return score if perspective == 0 else -score


# ─────────────────────────────────────────────────────────────────────────────
# Move ordering
# ─────────────────────────────────────────────────────────────────────────────

def _mvv_lva(board, move) -> int:
    """Most-Valuable-Victim / Least-Valuable-Attacker key (lower = try first)."""
    tr, tc = move["to_pos"]; fr, fc = move["from_pos"]
    victim   = board.get(tr, tc)
    attacker = board.get(fr, fc)
    if victim and attacker:
        return -(_pval(victim.piece_type) * 10 - _pval(attacker.piece_type))
    return 0


def _sort_moves(board, moves, tt_move=None, killers=None, history=None):
    """
    Priority order:
      1. TT best move from previous iteration
      2. Winning/equal captures (MVV-LVA)
      3. Promotions
      4. Killer moves (quiet refutations at same depth)
      5. History-heuristic quiet moves
      6. Everything else
    """
    def key(m):
        if (tt_move and m["from_pos"] == tt_move[0]
                and m["to_pos"] == tt_move[1]):
            return -100_000
        if m.get("captured_uid"):
            return -10_000 + _mvv_lva(board, m)
        if m.get("needs_promotion"):
            return -9_000
        if killers and m in killers:
            return -8_000 + killers.index(m)
        if history:
            h = history.get((m["from_pos"], m["to_pos"]), 0)
            return -h
        return 0
    moves.sort(key=key)


# ─────────────────────────────────────────────────────────────────────────────
# Transposition table
# ─────────────────────────────────────────────────────────────────────────────
_TT: dict  = {}
_TT_MAX    = 1_000_000
_EXACT     = 0
_LOWER     = 1   # fail-high / lower bound
_UPPER     = 2   # fail-low  / upper bound


def _tt_probe(key, depth, alpha, beta):
    e = _TT.get(key)
    if e and e[0] >= depth:
        flag, val = e[1], e[2]
        if flag == _EXACT:                  return val
        if flag == _LOWER and val >= beta:  return val
        if flag == _UPPER and val <= alpha: return val
    return None


def _tt_store(key, depth, val, flag, best_fp=None, best_tp=None):
    if len(_TT) >= _TT_MAX:
        _TT.clear()
    _TT[key] = (depth, flag, val, best_fp, best_tp)


def _tt_best(key):
    e = _TT.get(key)
    return (e[3], e[4]) if e and e[3] is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# Quiescence search — captures only, avoids horizon effect
# ─────────────────────────────────────────────────────────────────────────────

def _quiesce(board, alpha, beta, owner, maximizing, depth_left, deadline, nodes):
    nodes[0] += 1
    if nodes[0] & 255 == 0 and time.time() > deadline:
        raise TimeoutError

    # Stand-pat score
    raw      = quick_eval(board, 0)
    stand    = raw if maximizing else -raw
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    if depth_left <= 0:
        return alpha

    current = owner if maximizing else 1 - owner
    caps    = [m for m in GEN.all_moves(board, current, legal_only=True)
               if m.get("captured_uid")]
    caps.sort(key=lambda m: _mvv_lva(board, m))

    for m in caps:
        val = -_quiesce(board.apply_move(m), -beta, -alpha,
                        owner, not maximizing, depth_left - 1, deadline, nodes)
        if val >= beta:
            return beta
        if val > alpha:
            alpha = val
    return alpha


# ─────────────────────────────────────────────────────────────────────────────
# Alpha-beta search with null-move pruning, killers, history heuristic
# ─────────────────────────────────────────────────────────────────────────────

def _alphabeta(board, depth, alpha, beta, maximizing, owner,
               killers, history, nodes, deadline):
    nodes[0] += 1
    if nodes[0] & 511 == 0 and time.time() > deadline:
        raise TimeoutError

    pos_key = board.position_key()
    cached  = _tt_probe(pos_key, depth, alpha, beta)
    if cached is not None:
        return cached

    result = GEN.game_result(board)
    if result == "checkmate":
        return -90_000 + (20 - depth)   # faster mate = higher score
    if result in ("stalemate", "50move", "repetition", "material"):
        return 0
    if depth == 0:
        return _quiesce(board, alpha, beta, owner, maximizing, 4, deadline, nodes)

    current  = owner if maximizing else 1 - owner
    in_check = GEN.is_in_check(board, current)

    # ── Null-move pruning ──────────────────────────────────────────────────
    # Skip our move; if even then the position is still >= beta, prune.
    if depth >= 3 and not in_check and not _is_endgame(board):
        R = 2
        null_b = board.clone()
        null_b.current_player = 1 - null_b.current_player
        null_b.en_passant_target = None
        try:
            null_val = -_alphabeta(
                null_b, depth - 1 - R, -beta, -beta + 1,
                not maximizing, owner, killers, history, nodes, deadline)
            if null_val >= beta:
                _tt_store(pos_key, depth, beta, _LOWER)
                return beta
        except TimeoutError:
            raise

    moves = GEN.all_moves(board, current, legal_only=True)
    if not moves:
        return 0

    tt_hint = _tt_best(pos_key)
    kl      = killers.get(depth, [])
    _sort_moves(board, moves, tt_move=tt_hint, killers=kl, history=history)

    orig_alpha = alpha
    best_val   = -999_999 if maximizing else 999_999
    best_fp    = best_tp = None

    for m in moves:
        child = board.apply_move(m)
        val   = _alphabeta(child, depth - 1, alpha, beta,
                           not maximizing, owner, killers, history, nodes, deadline)
        fp, tp = m["from_pos"], m["to_pos"]
        if maximizing:
            if val > best_val:
                best_val = val; best_fp = fp; best_tp = tp
            alpha = max(alpha, val)
            if alpha >= beta:
                # Beta cutoff — update killers and history
                if not m.get("captured_uid"):
                    kl = killers.setdefault(depth, [])
                    if m not in kl:
                        kl.insert(0, m)
                        if len(kl) > 2: kl.pop()
                    history[(fp, tp)] = history.get((fp, tp), 0) + depth * depth
                _tt_store(pos_key, depth, best_val, _LOWER, best_fp, best_tp)
                return best_val
        else:
            if val < best_val:
                best_val = val; best_fp = fp; best_tp = tp
            beta = min(beta, val)
            if beta <= alpha:
                if not m.get("captured_uid"):
                    kl = killers.setdefault(depth, [])
                    if m not in kl:
                        kl.insert(0, m)
                        if len(kl) > 2: kl.pop()
                    history[(fp, tp)] = history.get((fp, tp), 0) + depth * depth
                _tt_store(pos_key, depth, best_val, _UPPER, best_fp, best_tp)
                return best_val

    flag = (_EXACT if orig_alpha < best_val < beta
            else (_LOWER if best_val >= beta else _UPPER))
    _tt_store(pos_key, depth, best_val, flag, best_fp, best_tp)
    return best_val


# ─────────────────────────────────────────────────────────────────────────────
# Public: get best move (iterative deepening + aspiration windows)
# ─────────────────────────────────────────────────────────────────────────────

def get_best_move(board, owner, elo_idx=4, time_limit=None):
    """
    Return the best legal move for `owner` at the requested ELO tier.
    Uses iterative deepening so the best result from completed iterations
    is always returned even if we time out mid-search.
    """
    level      = ELO_LEVELS[max(0, min(elo_idx, len(ELO_LEVELS) - 1))]
    max_depth  = level["depth"]
    noise      = level["noise"]
    blunder_r  = level["blunder"]
    tl         = time_limit if time_limit is not None else level["time"]

    print(f"[ai] think owner={owner} elo={level['elo']} max_depth={max_depth} time={tl:.1f}s")

    # Opening book
    if level["book"] and len(board.move_history) < 24:
        try:
            bm = book_move(board)
            if bm:
                return bm
        except Exception as e:
            log.warning("Book error: %s", e)

    moves = GEN.all_moves(board, owner, legal_only=True)
    if not moves:
        return None

    deadline = time.time() + tl * 0.92
    nodes    = [0]
    killers  = {}
    history  = {}

    # Depth-1 baseline sort (fast)
    scored = []
    for m in moves:
        sc = quick_eval(board.apply_move(m), 0)
        if noise:
            sc += random.randint(-noise, noise)
        scored.append([sc, m])
    scored.sort(key=lambda x: -x[0])
    best_move = scored[0][1]

    # Iterative deepening
    for depth in range(1, max_depth + 1):
        if time.time() > deadline:
            break
        prev_best = scored[0][0]
        asp_lo    = prev_best - 120 if depth >= 2 else -999_999
        asp_hi    = prev_best + 120 if depth >= 2 else  999_999
        new_scored = []
        try:
            for sc, m in scored:
                if time.time() > deadline:
                    break
                child = board.apply_move(m)
                val   = _alphabeta(child, depth - 1, asp_lo, asp_hi, False,
                                   owner, killers, history, nodes, deadline)
                if noise:
                    val += random.randint(-noise // 2, noise // 2)
                new_scored.append([val, m])
            new_scored.sort(key=lambda x: -x[0])
            if new_scored:
                scored    = new_scored
                best_move = scored[0][1]
        except TimeoutError:
            break

    # Blunder injection for low ELO realism
    if blunder_r > 0 and random.random() < blunder_r:
        pool = scored[max(1, len(scored) // 3):]
        if pool:
            print(f"[ai] Blunder injected (ELO {level['elo']})")
            return random.choice(pool)[1]

    print(f"[ai] Best move: {best_move['from_pos']}->{best_move['to_pos']} "
          f"nodes={nodes[0]} depth={max_depth}")
    return best_move


# ─────────────────────────────────────────────────────────────────────────────
# Mate-in-N search — fast dedicated search for forced mates
# Returns (N, move) where N is number of FULL moves, or (None, None).
# ─────────────────────────────────────────────────────────────────────────────

def find_mate_in_n(board, owner, max_n=5, deadline_secs=3.0):
    """
    Efficient forced-mate search using a dedicated alpha-beta with a mate window.

    Algorithm:
      - Iterate over N = 1, 2, … max_n full moves
      - Each iteration searches 2N-1 half-moves (plies)
      - Ordering: captures, then checks, then rest — prunes quickly
      - No slow quick_eval at leaf: we only care about checkmate vs not-mate
      - Early exit per ply the moment one mating line is confirmed for ALL opponent
        defences (i.e. opponent has no escape)

    Returns (N, best_move) or (None, None) if no forced mate in budget.
    """
    deadline = time.time() + deadline_secs
    nodes    = [0]
    MATE_SC  = 100_000

    def _gives_check(b, mv):
        """Lightweight: does this move leave the opponent in check?"""
        try:
            return GEN.is_in_check(b.apply_move(mv), 1 - b.current_player)
        except Exception:
            return False

    def _order(b, mvs):
        """Captures and checks first for faster beta-cutoffs."""
        def key(m):
            if m.get("captured_uid"):   return 0
            if _gives_check(b, m):      return 1
            return 2
        mvs.sort(key=key)

    def _search(b, depth, alpha, beta, our_turn):
        """
        Returns MATE_SC + remaining_depth if forced mate, else <= 0.
        our_turn=True  → we play (maximising: looking for mate)
        our_turn=False → opponent plays (minimising: trying to escape)
        """
        nodes[0] += 1
        if nodes[0] & 255 == 0 and time.time() > deadline:
            raise TimeoutError

        result = GEN.game_result(b)
        if result == "checkmate":
            # More depth remaining = faster mate = better
            return MATE_SC + depth
        if result in ("stalemate", "50move", "repetition", "material"):
            return 0
        if depth == 0:
            # Reached leaf without checkmate — not a forced mate on this line
            return -1

        current = owner if our_turn else 1 - owner
        moves   = GEN.all_moves(b, current, legal_only=True)
        if not moves:
            return 0

        _order(b, moves)

        if our_turn:
            best = 0
            for m in moves:
                val = _search(b.apply_move(m), depth - 1, alpha, beta, False)
                if val >= MATE_SC:
                    return val          # found a mating line from this move
                best  = max(best, val)
                alpha = max(alpha, val)
                if alpha >= beta:
                    break
            return best
        else:
            # Opponent tries every escape; if any escape exists → not forced mate
            worst = MATE_SC + 9999
            for m in moves:
                val = _search(b.apply_move(m), depth - 1, alpha, beta, True)
                if val < MATE_SC:
                    return 0           # opponent found an escape; this line fails
                worst = min(worst, val)
                beta  = min(beta, val)
                if alpha >= beta:
                    break
            return worst

    try:
        for n in range(1, max_n + 1):
            if time.time() > deadline:
                return None, None
            plies = n * 2 - 1          # mate in N full moves = 2N-1 half-moves
            moves = GEN.all_moves(board, owner, legal_only=True)
            _order(board, moves)
            for m in moves:
                if time.time() > deadline:
                    return None, None
                try:
                    val = _search(board.apply_move(m), plies - 1,
                                  -999_999, 999_999, False)
                    if val >= MATE_SC:
                        print(f"[ai] Mate in {n}: {m['from_pos']}->{m['to_pos']} "
                              f"nodes={nodes[0]}")
                        return n, m
                except TimeoutError:
                    return None, None
    except TimeoutError:
        pass

    return None, None

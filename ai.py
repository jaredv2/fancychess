"""
ai.py  -  Fairy Chess AI
=========================
Minimax + Alpha-Beta with:
  - Piece-Square Tables (PSTs) for positional awareness
  - Material + mobility + pawn structure evaluation
  - ELO-rated levels (800 to 2200) with realistic play quality
  - Iterative deepening with time limit
  - Move ordering (MVV-LVA captures first)
  - quick_eval() for the eval bar (no search, just static)
"""

import time, random
from logic import Board, MoveGenerator

print("[DEBUG ai] ai.py loaded")

GENERATOR = MoveGenerator()

# ELO levels
ELO_LEVELS = [
    {"name": "Beginner",    "elo": 800,  "depth": 1, "noise": 200, "blunder": 0.35},
    {"name": "Casual",      "elo": 1000, "depth": 1, "noise":  80, "blunder": 0.18},
    {"name": "Club",        "elo": 1200, "depth": 2, "noise":  40, "blunder": 0.08},
    {"name": "Intermediate","elo": 1400, "depth": 2, "noise":  15, "blunder": 0.03},
    {"name": "Advanced",    "elo": 1800, "depth": 3, "noise":   5, "blunder": 0.01},
    {"name": "Master",      "elo": 2200, "depth": 4, "noise":   0, "blunder": 0.00},
]

MATERIAL = {
    "King": 20000, "Queen": 900, "Rook": 500,
    "Bishop": 330, "Knight": 320, "Pawn": 100,
}

def _mirror(t): return list(reversed(t))

PST_PAWN_W = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
PST_KNIGHT = [
   -50,-40,-30,-30,-30,-30,-40,-50,
   -40,-20,  0,  0,  0,  0,-20,-40,
   -30,  0, 10, 15, 15, 10,  0,-30,
   -30,  5, 15, 20, 20, 15,  5,-30,
   -30,  0, 15, 20, 20, 15,  0,-30,
   -30,  5, 10, 15, 15, 10,  5,-30,
   -40,-20,  0,  5,  5,  0,-20,-40,
   -50,-40,-30,-30,-30,-30,-40,-50,
]
PST_BISHOP = [
   -20,-10,-10,-10,-10,-10,-10,-20,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -10,  0,  5, 10, 10,  5,  0,-10,
   -10,  5,  5, 10, 10,  5,  5,-10,
   -10,  0, 10, 10, 10, 10,  0,-10,
   -10, 10, 10, 10, 10, 10, 10,-10,
   -10,  5,  0,  0,  0,  0,  5,-10,
   -20,-10,-10,-10,-10,-10,-10,-20,
]
PST_ROOK = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]
PST_QUEEN = [
   -20,-10,-10, -5, -5,-10,-10,-20,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -10,  0,  5,  5,  5,  5,  0,-10,
    -5,  0,  5,  5,  5,  5,  0, -5,
     0,  0,  5,  5,  5,  5,  0, -5,
   -10,  5,  5,  5,  5,  5,  0,-10,
   -10,  0,  5,  0,  0,  0,  0,-10,
   -20,-10,-10, -5, -5,-10,-10,-20,
]
PST_KING_MG = [
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -20,-30,-30,-40,-40,-30,-30,-20,
   -10,-20,-20,-20,-20,-20,-20,-10,
    20, 20,  0,  0,  0,  0, 20, 20,
    20, 30, 10,  0,  0, 10, 30, 20,
]

PST_MAP = {
    "Pawn":   (PST_PAWN_W, _mirror(PST_PAWN_W)),
    "Knight": (PST_KNIGHT, _mirror(PST_KNIGHT)),
    "Bishop": (PST_BISHOP, _mirror(PST_BISHOP)),
    "Rook":   (PST_ROOK,   _mirror(PST_ROOK)),
    "Queen":  (PST_QUEEN,  _mirror(PST_QUEEN)),
    "King":   (PST_KING_MG, _mirror(PST_KING_MG)),
}


def _pst(piece):
    name = piece.piece_type.name
    if name not in PST_MAP: return 0
    tbl = PST_MAP[name][piece.owner]
    idx = piece.row * 8 + piece.col
    return tbl[idx] if 0 <= idx < 64 else 0


def quick_eval(board: Board, perspective: int = 0) -> int:
    """Static evaluation (no search). centipawns, positive = good for white."""
    score = 0
    for p in board.all_pieces():
        mat = MATERIAL.get(p.piece_type.name, 150)
        val = mat + _pst(p)
        score += val if p.owner == 0 else -val
    # Mobility
    for p in board.all_pieces():
        mob = len(GENERATOR.get_moves(p, board, legal_only=False)) * 3
        score += mob if p.owner == 0 else -mob
    return score if perspective == 0 else -score


def _move_order_key(board, move):
    """MVV-LVA: big captures first."""
    tr, tc = move["to_pos"]
    target = board.get(tr, tc)
    fr, fc = move["from_pos"]
    attacker = board.get(fr, fc)
    if target and attacker:
        return -(10 * MATERIAL.get(target.piece_type.name, 100)
                 - MATERIAL.get(attacker.piece_type.name, 100))
    return 0


def minimax(board, depth, alpha, beta, maximizing, max_player, nodes, deadline):
    nodes[0] += 1
    if nodes[0] % 512 == 0 and time.time() > deadline:
        raise TimeoutError

    result = GENERATOR.game_result(board)
    if result == "checkmate":
        return -90000 + (100 - depth)
    if result in ("stalemate", "50move", "repetition", "material"):
        return 0
    if depth == 0:
        v = quick_eval(board, 0)
        return v if max_player == 0 else -v

    current = max_player if maximizing else 1 - max_player
    moves = GENERATOR.all_moves(board, current, legal_only=True)
    if not moves: return 0

    moves.sort(key=lambda m: _move_order_key(board, m))

    if maximizing:
        best = -999999
        for m in moves:
            val = minimax(board.apply_move(m), depth-1, alpha, beta, False, max_player, nodes, deadline)
            if val > best: best = val
            alpha = max(alpha, val)
            if beta <= alpha: break
        return best
    else:
        best = 999999
        for m in moves:
            val = minimax(board.apply_move(m), depth-1, alpha, beta, True, max_player, nodes, deadline)
            if val < best: best = val
            beta = min(beta, val)
            if beta <= alpha: break
        return best


def get_best_move(board: Board, owner: int, elo_idx: int = 4, time_limit: float = 8.0):
    """Find best move for owner at given ELO level index."""
    level = ELO_LEVELS[max(0, min(elo_idx, len(ELO_LEVELS)-1))]
    depth, noise, blunder_rate = level["depth"], level["noise"], level["blunder"]
    print(f"[DEBUG ai] searching elo={level['elo']} depth={depth} owner={owner}")

    moves = GENERATOR.all_moves(board, owner, legal_only=True)
    if not moves:
        print("[DEBUG ai] no legal moves")
        return None

    # Random blunder
    if blunder_rate > 0 and random.random() < blunder_rate:
        chosen = random.choice(moves)
        print(f"[DEBUG ai] blunder: {chosen['from_pos']}->{chosen['to_pos']}")
        return chosen

    deadline = time.time() + time_limit * 0.9
    best_move = moves[0]
    nodes = [0]

    try:
        for d in range(1, depth + 1):
            if time.time() > deadline: break
            c_best = None; c_score = -999999
            moves.sort(key=lambda m: _move_order_key(board, m))
            for move in moves:
                child = board.apply_move(move)
                score = minimax(child, d-1, -999999, 999999, False, owner, nodes, deadline)
                if noise > 0:
                    score += random.randint(-noise, noise)
                if score > c_score:
                    c_score = score; c_best = move
            if c_best: best_move = c_best
    except TimeoutError:
        print(f"[DEBUG ai] timeout at {nodes[0]} nodes")

    print(f"[DEBUG ai] result: {best_move['from_pos']}->{best_move['to_pos']} nodes={nodes[0]}")
    return best_move

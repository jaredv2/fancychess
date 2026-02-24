"""
test_cli.py - CLI verification of the Fairy Chess engine
=========================================================
Tests:
  1. S-Move over a leaping obstacle
  2. Pawn double-step first move
  3. Universal castling (horizontal)
  4. AI move generation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from logic import (
    Board, Piece, MoveGenerator, MoveRule, Leg, PieceType,
    build_default_pieces, parse_segment_string
)
from ai import get_best_move

PIECES = build_default_pieces()
GEN = MoveGenerator()

print("=" * 60)
print("FAIRY CHESS ENGINE - CLI TEST SUITE")
print("=" * 60)

# ─────────────────────────────────────────────────────────────
# TEST 1: S-Move over a leaping obstacle
# ─────────────────────────────────────────────────────────────
print("\n[TEST 1] S-Move with leap over obstacle")
print("-" * 40)
"""
Setup:
  row 0: SMover (white) at (0,0)
  row 2: Obstacle (enemy pawn) at (2,0)  ← in the path of leg 1 (leap=True skips it)
  Destination: (3,2) via path (0,0) -[2 forward leap]-> (2,0) -[2 right]-> (2,2) -[1 forward]-> (3,2)
  
  The first leg goes dx=2, dy=0 with leapable=True, so it JUMPS from (0,0) to (2,0),
  skipping any piece at (1,0) and (2,0)... wait: let's be precise.
  
  Actually with steps=1 and dx=2: one application of vector (2,0) = lands at (2,0).
  Leapable=True means blockers BEFORE the final square of THIS leg are ignored.
  Since steps=1, there are NO intermediate squares on this leg — it's a direct jump to (2,0).
  Then leg 2: (0,2) from (2,0) to (2,2) — must be clear.
  Then leg 3: (1,0) from (2,2) to (3,2).
  
  We'll place a piece AT (2,0) to show the S-move lands on (2,0) as intermediate
  and still proceeds. Since (2,0) is only an intermediate point (not the final dest),
  the piece there does NOT block a leapable leg.
"""

board1 = Board(8, 8)

# White SMover at (0,0)
s_mover = Piece(PIECES["SMover"], owner=0, row=0, col=0)
board1.place(s_mover)
print(f"  Placed: {s_mover}")

# Enemy pawn at (2,0) — sits on intermediate trace point of leg 1
obstacle = Piece(PIECES["Pawn"], owner=1, row=2, col=0)
board1.place(obstacle)
print(f"  Obstacle (enemy): {obstacle}")

# Another piece at (1,0) to confirm it doesn't block the leaping leg
blocker2 = Piece(PIECES["Pawn"], owner=1, row=1, col=0)
board1.place(blocker2)
print(f"  Extra blocker at (1,0): {blocker2}")

board1.display()

moves = GEN.get_moves(s_mover, board1)
print(f"  Generated {len(moves)} S-move(s):")
for m in moves:
    print(f"    {m['from_pos']} -> {m['to_pos']} (capture: {m['captured_uid'] is not None})")

# Expect destination at (3, 2) if clear
expected_dest = (3, 2)
found = any(m["to_pos"] == expected_dest for m in moves)
print(f"\n  RESULT: S-move to {expected_dest} found = {'✓ PASS' if found else '✗ FAIL'}")

# ─────────────────────────────────────────────────────────────
# TEST 2: Pawn double-step on first move
# ─────────────────────────────────────────────────────────────
print("\n[TEST 2] Pawn double-step (first_move_only)")
print("-" * 40)

board2 = Board(8, 8)
pawn = Piece(PIECES["Pawn"], owner=0, row=1, col=3)
board2.place(pawn)
print(f"  Placed: {pawn} (has_moved={pawn.has_moved})")
board2.display()

moves2 = GEN.get_moves(pawn, board2)
dests = [m["to_pos"] for m in moves2]
print(f"  Available destinations: {dests}")

# Should include (2,3) single step AND (3,3) double step
single_ok = (2, 3) in dests
double_ok = (3, 3) in dests
print(f"  Single step (2,3): {'✓ PASS' if single_ok else '✗ FAIL'}")
print(f"  Double step (3,3): {'✓ PASS' if double_ok else '✗ FAIL'}")

# Now mark as moved, double step should disappear
pawn.has_moved = True
moves2b = GEN.get_moves(pawn, board2)
dests2b = [m["to_pos"] for m in moves2b]
double_gone = (3, 3) not in dests2b
print(f"  Double step gone after has_moved=True: {'✓ PASS' if double_gone else '✗ FAIL'}")

# ─────────────────────────────────────────────────────────────
# TEST 3: Universal Castling (horizontal)
# ─────────────────────────────────────────────────────────────
print("\n[TEST 3] Universal Castling (horizontal)")
print("-" * 40)

board3 = Board(8, 8)
king = Piece(PIECES["King"], owner=0, row=0, col=4)
rook = Piece(PIECES["Rook"], owner=0, row=0, col=7)
board3.place(king)
board3.place(rook)
print(f"  King at {(king.row, king.col)}, Rook at {(rook.row, rook.col)}")
board3.display()

castle_moves = [m for m in GEN.get_moves(king, board3) if m.get("castling")]
print(f"  Castling moves found: {len(castle_moves)}")
for m in castle_moves:
    print(f"    King {m['from_pos']} -> {m['to_pos']}, Rook -> {m['castling']['to_pos']}")

cast_ok = len(castle_moves) > 0
print(f"  RESULT: Castling detected = {'✓ PASS' if cast_ok else '✗ FAIL'}")

# Apply the castle
if castle_moves:
    new_board = board3.apply_move(castle_moves[0])
    new_board.display()
    print(f"  King now at: ({king.row},{king.col}) -> check new board")

# ─────────────────────────────────────────────────────────────
# TEST 4: Parse segment string from GUI
# ─────────────────────────────────────────────────────────────
print("\n[TEST 4] parse_segment_string()")
print("-" * 40)

seg = "0,1,2,true; 1,0,2; 0,1,1"
legs = parse_segment_string(seg)
print(f"  Input: '{seg}'")
print(f"  Parsed legs: {legs}")
expected_legs = [
    Leg(0, 1, 2, True),
    Leg(1, 0, 2, False),
    Leg(0, 1, 1, False),
]
parse_ok = (
    len(legs) == 3 and
    legs[0].dx == 0 and legs[0].dy == 1 and legs[0].steps == 2 and legs[0].leapable == True and
    legs[1].dx == 1 and legs[1].dy == 0 and legs[1].steps == 2 and
    legs[2].dx == 0 and legs[2].dy == 1 and legs[2].steps == 1
)
print(f"  RESULT: Parsed correctly = {'✓ PASS' if parse_ok else '✗ FAIL'}")

# ─────────────────────────────────────────────────────────────
# TEST 5: AI picks a move
# ─────────────────────────────────────────────────────────────
print("\n[TEST 5] AI - get_best_move()")
print("-" * 40)

board5 = Board(8, 8)
wk = Piece(PIECES["King"], owner=0, row=0, col=4)
wp = Piece(PIECES["Pawn"], owner=0, row=1, col=4)
bk = Piece(PIECES["King"], owner=1, row=7, col=4)
bp = Piece(PIECES["Pawn"], owner=1, row=6, col=4)
for p in [wk, wp, bk, bp]:
    board5.place(p)
board5.display()

best = get_best_move(board5, owner=0, depth=2)
if best:
    print(f"  AI chose: {best['from_pos']} -> {best['to_pos']}")
    print(f"  RESULT: AI returned a move = ✓ PASS")
else:
    print(f"  RESULT: AI returned None = ✗ FAIL")

# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST SUITE COMPLETE")
print("=" * 60)

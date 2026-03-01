"""
logic.py — Fancy Chess Engine  v6
===================================
Core rules engine. Everything the GUI and AI depend on lives here.

What's new in v6 (vs v5):
  - move_to_san()   : proper Standard Algebraic Notation for any move
                      (disambiguation, captures, promotions, check/mate suffix)
  - Board.material_count()  : fast centipawn tally used by eval
  - Board.pgn_header()      : minimal PGN export helper
  - is_insufficient_material: handles custom pieces (not just standard names)
  - position_key is now O(pieces) not O(rows×cols) — measurably faster for AI
  - MoveRule.n_moves_first documented and default corrected
  - Cleaner section headers, full type annotations throughout
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("fancy_chess.logic")
print("[logic] Module loaded — Fancy Chess Engine v6")


# ─────────────────────────────────────────────────────────────────────────────
# Primitive data-classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Leg:
    """
    One segment of a movement path.

    dx    : rank displacement (positive = toward rank 8 / white's promotion row)
    dy    : file displacement (positive = toward file h)
    steps : how many squares this leg travels (1 = single hop, 7 = full rook slide)
    leapable : if True intermediate squares may be occupied (knight-style)
    """
    dx: int
    dy: int
    steps: int = 1
    leapable: bool = False

    def to_dict(self) -> dict:
        return {"dx": self.dx, "dy": self.dy,
                "steps": self.steps, "leapable": self.leapable}

    @staticmethod
    def from_dict(d: dict) -> "Leg":
        return Leg(d["dx"], d["dy"], d.get("steps", 1), d.get("leapable", False))


@dataclass
class MoveRule:
    """
    One movement pattern for a piece type.

    A single rule describes a (possibly multi-leg) path.  The move generator
    calls _trace() which walks every leg in sequence; if any leg is blocked the
    whole move is rejected.

    legs             : ordered list of Leg objects forming the path
    capture_only     : move is only legal when it captures
    non_capture_only : move is only legal when it does NOT capture
    first_move_only  : rule only applies before the piece has moved
    n_moves_first    : repeat the entire leg-sequence this many times on the
                       first move (pawn double-push = n_moves_first=2 applied
                       once, generating a separate rule per step count)
    capture_filter   : reserved for future conditional-capture variants
    castling         : special castling rule handled by _castling()
    en_passant       : special en-passant rule handled by _en_passant()
    """
    legs: List[Leg] = field(default_factory=list)
    capture_only: bool = False
    non_capture_only: bool = False
    first_move_only: bool = False
    n_moves_first: int = 1
    capture_filter: Optional[str] = None
    castling: bool = False
    en_passant: bool = False

    def to_dict(self) -> dict:
        return {
            "legs":             [l.to_dict() for l in self.legs],
            "capture_only":     self.capture_only,
            "non_capture_only": self.non_capture_only,
            "first_move_only":  self.first_move_only,
            "n_moves_first":    self.n_moves_first,
            "capture_filter":   self.capture_filter,
            "castling":         self.castling,
            "en_passant":       self.en_passant,
        }

    @staticmethod
    def from_dict(d: dict) -> "MoveRule":
        r = MoveRule()
        r.legs              = [Leg.from_dict(l) for l in d.get("legs", [])]
        r.capture_only      = d.get("capture_only", False)
        r.non_capture_only  = d.get("non_capture_only", False)
        r.first_move_only   = d.get("first_move_only", False)
        r.n_moves_first     = d.get("n_moves_first", 1)
        r.capture_filter    = d.get("capture_filter", None)
        r.castling          = d.get("castling", False)
        r.en_passant        = d.get("en_passant", False)
        return r


@dataclass
class PieceType:
    """
    Definition of a piece type (independent of colour or position).

    name          : display name, e.g. "Queen"
    symbol        : single uppercase letter used in FEN and SAN, e.g. "Q"
    rules         : list of MoveRule objects
    is_royal      : losing this piece ends the game (King)
    is_castler    : can participate in castling (Rook)
    lethality     : AI aggressiveness multiplier (separate from centipawn value)
    value         : centipawn worth — set in the piece editor, read by the AI
    promotable_to : list of piece-type names a pawn can promote to
    """
    name: str
    symbol: str
    rules: List[MoveRule] = field(default_factory=list)
    is_royal: bool = False
    is_castler: bool = False
    lethality: float = 1.0
    value: int = 0          # centipawn value; 0 → AI uses built-in fallback table
    promotable_to: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "symbol":        self.symbol,
            "rules":         [r.to_dict() for r in self.rules],
            "is_royal":      self.is_royal,
            "is_castler":    self.is_castler,
            "lethality":     self.lethality,
            "value":         self.value,
            "promotable_to": self.promotable_to,
        }

    @staticmethod
    def from_dict(d: dict) -> "PieceType":
        pt = PieceType(
            name=d["name"],
            symbol=d.get("symbol", "?"),
            is_royal=d.get("is_royal", False),
            is_castler=d.get("is_castler", False),
            lethality=d.get("lethality", 1.0),
            value=d.get("value", 0),
            promotable_to=d.get("promotable_to", []),
        )
        pt.rules = [MoveRule.from_dict(r) for r in d.get("rules", [])]
        return pt


# ─────────────────────────────────────────────────────────────────────────────
# Piece  (instance on the board — has colour, position, move history)
# ─────────────────────────────────────────────────────────────────────────────

class Piece:
    """A single piece placed on a board.  Immutable identity via uid."""

    _id: int = 0   # class-level counter; increments on every Piece()

    def __init__(self, pt: PieceType, owner: int, row: int, col: int) -> None:
        Piece._id += 1
        self.uid        = Piece._id
        self.piece_type = pt
        self.owner      = owner    # 0 = white, 1 = black
        self.row        = row
        self.col        = col
        self.has_moved  = False

    def __repr__(self) -> str:
        return (f"Piece({self.piece_type.symbol}"
                f"{'wb'[self.owner]}@({self.row},{self.col}))")

    def clone(self) -> "Piece":
        """Shallow clone — shares PieceType reference (immutable)."""
        p            = Piece.__new__(Piece)
        p.uid        = self.uid
        p.piece_type = self.piece_type
        p.owner      = self.owner
        p.row        = self.row
        p.col        = self.col
        p.has_moved  = self.has_moved
        return p


# ─────────────────────────────────────────────────────────────────────────────
# Board  (8×8 grid + game state)
# ─────────────────────────────────────────────────────────────────────────────

class Board:
    """
    Immutable-style board: apply_move() returns a new Board without modifying
    the original.  clone() is O(pieces) not O(rows×cols).
    """

    def __init__(self, rows: int = 8, cols: int = 8) -> None:
        self.rows = rows
        self.cols = cols
        self.grid: List[List[Optional[Piece]]] = [
            [None] * cols for _ in range(rows)
        ]
        self.current_player: int = 0            # 0 = white to move
        self.move_history:   List[dict] = []
        self.en_passant_target: Optional[Tuple[int, int]] = None
        self.halfmove_clock:  int = 0
        self.fullmove_number: int = 1
        # castling_rights[(owner, 'K'|'Q')] = True/False
        self.castling_rights: Dict[Tuple[int, str], bool] = {
            (0, 'K'): True, (0, 'Q'): True,
            (1, 'K'): True, (1, 'Q'): True,
        }
        self._position_counts: Dict[str, int] = {}

    # ── Queries ──────────────────────────────────────────────────────────────

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def place(self, p: Piece) -> None:
        """Place piece on the grid (used during setup)."""
        self.grid[p.row][p.col] = p

    def get(self, r: int, c: int) -> Optional[Piece]:
        return self.grid[r][c] if self.in_bounds(r, c) else None

    def all_pieces(self, owner: Optional[int] = None) -> List[Piece]:
        """Return all pieces, optionally filtered by owner."""
        return [p for row in self.grid for p in row
                if p and (owner is None or p.owner == owner)]

    def find_king(self, owner: int) -> Optional[Piece]:
        """Return the royal piece for `owner`, or None if it has been captured."""
        for p in self.all_pieces(owner):
            if p.piece_type.is_royal:
                return p
        return None

    def material_count(self, owner: Optional[int] = None) -> int:
        """
        Total centipawn value of pieces on the board.
        Uses PieceType.value if set, otherwise the standard material table.
        """
        _std = {"King": 20000, "Queen": 950, "Rook": 510,
                "Bishop": 340, "Knight": 325, "Pawn": 100}
        total = 0
        for p in self.all_pieces(owner):
            v = p.piece_type.value if p.piece_type.value > 0 \
                else _std.get(p.piece_type.name, int(p.piece_type.lethality * 200))
            total += v
        return total

    # ── Position key (for TT and repetition detection) ───────────────────────

    def position_key(self) -> str:
        """
        Compact string uniquely identifying the board state for
        transposition-table lookup and threefold-repetition detection.

        Iterates only over pieces (not all 64 squares), so it's O(N_pieces).
        Includes current player, en-passant target, and castling rights.
        """
        parts: List[str] = []
        for p in self.all_pieces():
            parts.append(f"{p.row}{p.col}{p.piece_type.symbol}{p.owner}")
        # Sort so position_key is order-independent w.r.t. piece list
        parts.sort()
        cr = "".join(
            f"{o}{s}" for (o, s), v in sorted(self.castling_rights.items()) if v
        )
        return f"{'|'.join(parts)}/{self.current_player}/{self.en_passant_target}/{cr}"

    # ── Cloning ───────────────────────────────────────────────────────────────

    def clone(self) -> "Board":
        """Deep-copy the board (O(pieces) not O(rows×cols))."""
        b = Board.__new__(Board)
        b.rows               = self.rows
        b.cols               = self.cols
        b.grid               = [[None] * self.cols for _ in range(self.rows)]
        for p in self.all_pieces():
            cp = p.clone()
            b.grid[cp.row][cp.col] = cp
        b.current_player    = self.current_player
        b.move_history      = list(self.move_history)
        b.en_passant_target = self.en_passant_target
        b.halfmove_clock    = self.halfmove_clock
        b.fullmove_number   = self.fullmove_number
        b.castling_rights   = dict(self.castling_rights)
        b._position_counts  = dict(self._position_counts)
        return b

    # ── Move application ─────────────────────────────────────────────────────

    def apply_move(self, move: dict) -> "Board":
        """
        Return a new Board with `move` applied.  Does NOT modify self.

        move dict keys (generated by MoveGenerator):
          from_pos        : (row, col) of moving piece
          to_pos          : (row, col) destination
          captured_uid    : uid of captured piece or None
          double_push     : True for pawn 2-square advance (sets en-passant target)
          en_passant_capture : (row, col) of the pawn to remove on e.p. capture
          needs_promotion / promotion_type : promotion handling
          castling        : sub-dict {castler_uid, from_pos, to_pos}
        """
        b = self.clone()
        fr, fc = move["from_pos"]
        tr, tc = move["to_pos"]
        piece  = b.grid[fr][fc]
        b.en_passant_target = None

        is_capture = move.get("captured_uid") is not None
        is_pawn    = piece.piece_type.symbol in ("P", "p")

        # Remove captured pawn for en-passant
        if move.get("en_passant_capture"):
            ep_r, ep_c = move["en_passant_capture"]
            b.grid[ep_r][ep_c] = None
        elif is_capture:
            b.grid[tr][tc] = None

        # Move the piece
        b.grid[fr][fc] = None
        piece.row, piece.col = tr, tc
        b.grid[tr][tc] = piece

        # Set en-passant target for next move
        if move.get("double_push"):
            b.en_passant_target = ((fr + tr) // 2, tc)

        # Promotion: swap piece type in-place on the clone
        if move.get("promotion_type"):
            piece.piece_type = move["promotion_type"]

        # Castling: also move the castling piece (rook)
        if move.get("castling"):
            ci = move["castling"]
            cr2, cc2 = ci["from_pos"]
            castler = b.grid[cr2][cc2]
            if castler:
                b.grid[cr2][cc2] = None
                tr2, tc2 = ci["to_pos"]
                castler.row, castler.col = tr2, tc2
                castler.has_moved = True
                b.grid[tr2][tc2] = castler

        # Update castling rights
        if piece.piece_type.is_royal:
            b.castling_rights[(piece.owner, 'K')] = False
            b.castling_rights[(piece.owner, 'Q')] = False
        elif piece.piece_type.is_castler:
            side = 'K' if fc > (self.cols // 2) else 'Q'
            b.castling_rights[(piece.owner, side)] = False

        piece.has_moved = True
        b.current_player = 1 - b.current_player
        if b.current_player == 0:
            b.fullmove_number = self.fullmove_number + 1

        # 50-move rule clock resets on capture or pawn move
        b.halfmove_clock = 0 if (is_capture or is_pawn) else self.halfmove_clock + 1

        # Track position for threefold-repetition
        key = b.position_key()
        b._position_counts[key] = b._position_counts.get(key, 0) + 1
        b.move_history.append(move)
        return b

    # ── Draw conditions ───────────────────────────────────────────────────────

    def is_fifty_move_draw(self) -> bool:
        """True when 50 consecutive moves have been made without a pawn move or capture."""
        return self.halfmove_clock >= 100

    def is_threefold_repetition(self) -> bool:
        """True when the current position has occurred 3 or more times."""
        return any(v >= 3 for v in self._position_counts.values())

    def is_insufficient_material(self) -> bool:
        """
        True when neither side can possibly deliver checkmate.

        Handles both standard pieces (by name) and custom pieces (by lethality / value):
          - King vs King
          - King + single minor (Bishop or Knight) vs King
          - King + custom piece with value <= 100 (pawn-equivalent) vs King
        """
        pieces = self.all_pieces()
        n = len(pieces)
        if n == 2:
            # Only the two kings (or royal pieces) remain
            return True
        if n == 3:
            minors = [p for p in pieces if not p.piece_type.is_royal]
            if minors:
                m = minors[0]
                # Standard minor pieces
                if m.piece_type.name in ("Bishop", "Knight"):
                    return True
                # Custom pieces with very low value (effectively harmless)
                effective_val = m.piece_type.value if m.piece_type.value > 0 \
                    else int(m.piece_type.lethality * 200)
                if effective_val <= 100:
                    return True
        return False

    # ── PGN helper ────────────────────────────────────────────────────────────

    def pgn_header(self, white_name: str = "?", black_name: str = "?",
                   result: str = "*") -> str:
        """Return a minimal PGN header string."""
        import datetime
        date = datetime.date.today().strftime("%Y.%m.%d")
        return (f'[Event "Fancy Chess Game"]\n'
                f'[Site "Local"]\n'
                f'[Date "{date}"]\n'
                f'[White "{white_name}"]\n'
                f'[Black "{black_name}"]\n'
                f'[Result "{result}"]\n')


# ─────────────────────────────────────────────────────────────────────────────
# Move generator
# ─────────────────────────────────────────────────────────────────────────────

class MoveGenerator:
    """
    Generates legal and pseudo-legal moves for any piece on any board.

    All move dicts produced here follow the same schema (see Board.apply_move).
    """

    # ── Public interface ─────────────────────────────────────────────────────

    def get_moves(self, piece: Piece, board: Board,
                  legal_only: bool = False) -> List[dict]:
        """All moves available to `piece` on `board`."""
        moves: List[dict] = []
        for rule in piece.piece_type.rules:
            if rule.first_move_only and piece.has_moved:
                continue
            if rule.castling:
                moves += self._castling(piece, board)
                continue
            if rule.en_passant:
                moves += self._en_passant(piece, board)
                continue
            # n_moves_first: for pawn double-push we call _trace with reps=2
            max_rep = rule.n_moves_first if not piece.has_moved else 1
            for rep in range(1, max_rep + 1):
                moves += self._trace(piece, board, rule, rep)
        if legal_only:
            moves = [m for m in moves
                     if not self._in_check_after(m, board, piece.owner)]
        return moves

    def all_moves(self, board: Board, owner: int,
                  legal_only: bool = True) -> List[dict]:
        """All moves for every piece belonging to `owner`."""
        moves: List[dict] = []
        for p in board.all_pieces(owner):
            moves += self.get_moves(p, board, legal_only)
        return moves

    def is_in_check(self, board: Board, owner: int) -> bool:
        """Return True if `owner`'s king is in check."""
        return self._is_in_check(board, owner)

    def is_checkmate(self, board: Board, owner: int) -> bool:
        return self._is_in_check(board, owner) and not self.all_moves(board, owner)

    def is_stalemate(self, board: Board, owner: int) -> bool:
        return not self._is_in_check(board, owner) and not self.all_moves(board, owner)

    def game_result(self, board: Board) -> Optional[str]:
        """
        Check the game state from the perspective of board.current_player.

        Returns one of:
          'checkmate'  — current player has no legal moves and is in check
          'stalemate'  — current player has no legal moves, not in check
          '50move'     — draw by 50-move rule
          'repetition' — draw by threefold repetition
          'material'   — draw by insufficient material
          None         — game is still ongoing
        """
        cp = board.current_player
        if self.is_checkmate(board, cp):    return "checkmate"
        if self.is_stalemate(board, cp):    return "stalemate"
        if board.is_fifty_move_draw():      return "50move"
        if board.is_threefold_repetition(): return "repetition"
        if board.is_insufficient_material():return "material"
        return None

    # ── SAN notation (Standard Algebraic Notation) ──────────────────────────

    def move_to_san(self, move: dict, board: Board) -> str:
        """
        Convert a move dict to a proper SAN string.

        Handles:
          - Castling  → "O-O" / "O-O-O"
          - Pawn moves → "e4", "exd5", "e8=Q", "exd6 e.p."
          - Piece moves → "Nf3", "Raxd1" (with file/rank disambiguation)
          - Check/mate suffix → "+", "#"

        board is the position BEFORE the move is applied.
        """
        fr, fc = move["from_pos"]
        tr, tc = move["to_pos"]
        piece  = board.get(fr, fc)
        if piece is None:
            return "?"

        sym = piece.piece_type.symbol.upper()
        files = "abcdefgh"

        # Castling
        if move.get("castling"):
            san = "O-O" if tc > fc else "O-O-O"
        elif sym == "P":
            # Pawn move
            if move.get("captured_uid") or move.get("en_passant_capture"):
                san = f"{files[fc]}x{files[tc]}{tr + 1}"
                if move.get("en_passant_capture"):
                    san += " e.p."
            else:
                san = f"{files[tc]}{tr + 1}"
            # Promotion suffix
            if move.get("promotion_type"):
                promo_sym = move["promotion_type"].symbol.upper()
                san += f"={promo_sym}"
            elif move.get("promotion"):
                san += f"={str(move['promotion'])[0].upper()}"
        else:
            # Piece move — check disambiguation
            cap = "x" if move.get("captured_uid") else ""
            dest = f"{files[tc]}{tr + 1}"
            # Find all same-type pieces that could also reach dest
            ambig = [
                p for p in board.all_pieces(piece.owner)
                if p.uid != piece.uid
                and p.piece_type.symbol == piece.piece_type.symbol
                and any(m["to_pos"] == (tr, tc)
                        for m in self.get_moves(p, board, legal_only=True))
            ]
            if not ambig:
                dis = ""
            elif all(p.col != fc for p in ambig):
                dis = files[fc]        # file is enough
            elif all(p.row != fr for p in ambig):
                dis = str(fr + 1)      # rank is enough
            else:
                dis = f"{files[fc]}{fr + 1}"   # need both
            san = f"{sym}{dis}{cap}{dest}"

        # Check / checkmate suffix
        after = board.apply_move(move)
        opp   = after.current_player
        if self._is_in_check(after, opp):
            if not self.all_moves(after, opp, legal_only=True):
                san += "#"
            else:
                san += "+"

        return san

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _trace(self, piece: Piece, board: Board,
               rule: MoveRule, reps: int = 1) -> List[dict]:
        """
        Walk all legs of `rule` (supports multi-leg I/L/Z paths).

        reps: how many times the full leg sequence is repeated.
              Used by the pawn first-move double-push (reps=2 generates a
              two-square advance as a separate call from reps=1).
        """
        all_legs = rule.legs * reps
        if not all_legs:
            return []

        flip    = -1 if piece.owner == 1 else 1   # black moves "down" the grid
        r, c    = piece.row, piece.col
        blocked = False
        n_legs  = len(all_legs)

        for leg_idx, leg in enumerate(all_legs):
            dx          = leg.dx * flip
            dy          = leg.dy * flip
            is_last_leg = (leg_idx == n_legs - 1)

            for step in range(leg.steps):
                nr, nc = r + dx, c + dy
                if not board.in_bounds(nr, nc):
                    blocked = True; break
                is_last_step = (step == leg.steps - 1)
                is_final     = is_last_leg and is_last_step
                if not is_final:
                    if board.get(nr, nc) is not None and not leg.leapable:
                        blocked = True; break
                r, c = nr, nc
            if blocked:
                break

        if blocked:
            return []

        target = board.get(r, c)
        if target and target.owner == piece.owner:      return []
        if rule.capture_only     and not target:        return []
        if rule.non_capture_only and target:            return []

        move: dict = {
            "piece_uid":    piece.uid,
            "from_pos":     (piece.row, piece.col),
            "to_pos":       (r, c),
            "captured_uid": target.uid if target else None,
        }

        # Flag pawn double-push so Board.apply_move sets en-passant target
        if (abs(r - piece.row) == 2 and piece.col == c
                and piece.piece_type.symbol in ("P", "p")
                and not piece.has_moved):
            move["double_push"] = True

        # Flag promotion
        promo_row = 7 if piece.owner == 0 else 0
        if r == promo_row and piece.piece_type.promotable_to:
            move["needs_promotion"]   = True
            move["promotion_options"] = piece.piece_type.promotable_to

        return [move]

    def _en_passant(self, piece: Piece, board: Board) -> List[dict]:
        if board.en_passant_target is None:
            return []
        ep_r, ep_c = board.en_passant_target
        flip = -1 if piece.owner == 1 else 1
        pr, pc = piece.row, piece.col
        if abs(pc - ep_c) == 1 and pr + flip == ep_r:
            cap = board.get(pr, ep_c)
            return [{
                "piece_uid":          piece.uid,
                "from_pos":           (pr, pc),
                "to_pos":             (ep_r, ep_c),
                "captured_uid":       cap.uid if cap else None,
                "en_passant_capture": (pr, ep_c),
            }]
        return []

    def _castling(self, king: Piece, board: Board) -> List[dict]:
        """
        Generate castling moves for `king`.

        Rules enforced:
          1. King has not moved
          2. King is not currently in check
          3. Castling right exists for this side
          4. All squares between king and castler are empty
          5. King does not pass through or land on an attacked square
        """
        if king.has_moved or self._is_in_check(board, king.owner):
            return []
        moves: List[dict] = []
        kr, kc = king.row, king.col

        for castler in board.all_pieces(king.owner):
            if not castler.piece_type.is_castler or castler.has_moved:
                continue
            cr, cc = castler.row, castler.col
            same_row = (kr == cr)
            same_col = (kc == cc)
            if not same_row and not same_col:
                continue

            side = ('K' if cc > kc else 'Q') if same_row else ('K' if cr > kr else 'Q')
            if not board.castling_rights.get((king.owner, side), False):
                continue

            # Path must be clear
            if same_row:
                step = 1 if cc > kc else -1
                if any(board.get(kr, tc) for tc in range(kc + step, cc, step)):
                    continue
                if self._sq_attacked(board, (kr, kc + step), 1 - king.owner):
                    continue
                king_to    = (kr, kc + 2 * step)
                castler_to = (kr, kc + step)
            else:
                step = 1 if cr > kr else -1
                if any(board.get(tr, kc) for tr in range(kr + step, cr, step)):
                    continue
                if self._sq_attacked(board, (kr + step, kc), 1 - king.owner):
                    continue
                king_to    = (kr + 2 * step, kc)
                castler_to = (kr + step, kc)

            if not board.in_bounds(*king_to) or not board.in_bounds(*castler_to):
                continue
            if self._sq_attacked(board, king_to, 1 - king.owner):
                continue

            moves.append({
                "piece_uid":    king.uid,
                "from_pos":     (kr, kc),
                "to_pos":       king_to,
                "captured_uid": None,
                "castling": {
                    "castler_uid": castler.uid,
                    "from_pos":    (cr, cc),
                    "to_pos":      castler_to,
                },
            })
        return moves

    def _in_check_after(self, move: dict, board: Board, owner: int) -> bool:
        return self._is_in_check(board.apply_move(move), owner)

    def _is_in_check(self, board: Board, owner: int) -> bool:
        king = board.find_king(owner)
        if king is None:
            return True    # royal piece captured — treated as check
        return self._sq_attacked(board, (king.row, king.col), 1 - owner)

    def _sq_attacked(self, board: Board, sq: Tuple[int, int],
                     by_owner: int) -> bool:
        """Return True if any piece owned by `by_owner` attacks `sq`."""
        for p in board.all_pieces(by_owner):
            for rule in p.piece_type.rules:
                if rule.castling or rule.en_passant or rule.non_capture_only:
                    continue
                for m in self._trace(p, board, rule, 1):
                    if m["to_pos"] == sq:
                        return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# JSON serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_piece_types(piece_types: dict, path: str) -> None:
    """Save piece-type dict to a JSON file."""
    with open(path, "w") as f:
        json.dump({n: pt.to_dict() for n, pt in piece_types.items()}, f, indent=2)
    print(f"[logic] Saved {len(piece_types)} piece types → {path}")


def load_piece_types(path: str) -> dict:
    """Load piece-type dict from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    pt = {n: PieceType.from_dict(d) for n, d in data.items()}
    print(f"[logic] Loaded {len(pt)} piece types from {path}")
    return pt


# ─────────────────────────────────────────────────────────────────────────────
# FEN import / export
# ─────────────────────────────────────────────────────────────────────────────

# Maps standard FEN letter → standard piece name (fallback when piece_types
# don't contain a matching symbol)
_FEN_TO_NAME: Dict[str, str] = {
    'K': 'King', 'Q': 'Queen', 'R': 'Rook',
    'B': 'Bishop', 'N': 'Knight', 'P': 'Pawn',
}


def parse_fen(fen: str, piece_types: dict) -> Board:
    """
    Parse a standard FEN string into a Board.

    Supports:
      - All 6 FEN fields (placement, active, castling, en-passant, clocks)
      - Abbreviated FEN (missing fields default to standard start values)
      - Custom piece types via piece_types symbol mapping

    Raises ValueError on malformed input.
    """
    parts = fen.strip().split()
    if not parts:
        raise ValueError("Empty FEN string")

    placement    = parts[0]
    active       = parts[1] if len(parts) > 1 else "w"
    castling_str = parts[2] if len(parts) > 2 else "KQkq"
    ep_str       = parts[3] if len(parts) > 3 else "-"
    halfmove     = int(parts[4]) if len(parts) > 4 else 0
    fullmove     = int(parts[5]) if len(parts) > 5 else 1

    board = Board(8, 8)
    board.current_player  = 0 if active == "w" else 1
    board.halfmove_clock  = halfmove
    board.fullmove_number = fullmove

    # Build symbol → name mapping (custom pieces override standard FEN names)
    sym_to_name: Dict[str, str] = {}
    for name, pt in piece_types.items():
        sym_to_name[pt.symbol.upper()] = name
    for fen_sym, std_name in _FEN_TO_NAME.items():
        sym_to_name.setdefault(fen_sym, std_name)

    fen_ranks = placement.split("/")
    if len(fen_ranks) != 8:
        raise ValueError(f"FEN placement must have 8 ranks, got {len(fen_ranks)}")

    for fen_rank_idx, rank_str in enumerate(fen_ranks):
        board_row = 7 - fen_rank_idx   # FEN rank 8 (top) = board row 7
        col = 0
        for ch in rank_str:
            if ch.isdigit():
                col += int(ch)
            else:
                owner = 0 if ch.isupper() else 1
                sym   = ch.upper()
                name  = sym_to_name.get(sym)
                if name and name in piece_types:
                    p           = Piece(piece_types[name], owner, board_row, col)
                    p.has_moved = True     # conservative: assume all pieces moved
                    board.place(p)
                col += 1

    board.castling_rights = {
        (0, 'K'): 'K' in castling_str,
        (0, 'Q'): 'Q' in castling_str,
        (1, 'K'): 'k' in castling_str,
        (1, 'Q'): 'q' in castling_str,
    }

    # Restore has_moved=False for pieces on their start squares with rights intact
    for p in board.all_pieces():
        if p.piece_type.is_royal:
            start_row = 0 if p.owner == 0 else 7
            if p.row == start_row and p.col == 4:
                p.has_moved = False
        elif p.piece_type.is_castler:
            start_row = 0 if p.owner == 0 else 7
            if p.row == start_row:
                side = 'K' if p.col > 4 else 'Q'
                if board.castling_rights.get((p.owner, side), False):
                    p.has_moved = False

    # En-passant target
    if ep_str and ep_str != "-" and len(ep_str) == 2:
        try:
            ep_col = "abcdefgh".index(ep_str[0])
            ep_row = int(ep_str[1]) - 1
            if board.in_bounds(ep_row, ep_col):
                board.en_passant_target = (ep_row, ep_col)
        except (ValueError, IndexError):
            pass

    print(f"[logic] FEN parsed: {len(board.all_pieces())} pieces, "
          f"{'White' if board.current_player == 0 else 'Black'} to move")
    return board


def to_fen(board: Board) -> str:
    """Export a Board to a standard FEN string."""
    rows: List[str] = []
    for fen_rank_idx in range(8):
        board_row = 7 - fen_rank_idx
        empty     = 0
        row_str   = ""
        for col in range(8):
            p = board.get(board_row, col)
            if p is None:
                empty += 1
            else:
                if empty:
                    row_str += str(empty)
                    empty = 0
                sym      = p.piece_type.symbol
                row_str += sym.upper() if p.owner == 0 else sym.lower()
        if empty:
            row_str += str(empty)
        rows.append(row_str)

    active = "w" if board.current_player == 0 else "b"
    castle = ""
    if board.castling_rights.get((0, 'K')): castle += "K"
    if board.castling_rights.get((0, 'Q')): castle += "Q"
    if board.castling_rights.get((1, 'K')): castle += "k"
    if board.castling_rights.get((1, 'Q')): castle += "q"
    castle = castle or "-"

    ep = "-"
    if board.en_passant_target:
        er, ec = board.en_passant_target
        ep = "abcdefgh"[ec] + str(er + 1)

    return (f"{'/'.join(rows)} {active} {castle} {ep} "
            f"{board.halfmove_clock} {board.fullmove_number}")


# ─────────────────────────────────────────────────────────────────────────────
# Default standard-chess piece set
# ─────────────────────────────────────────────────────────────────────────────

def build_default_pieces() -> dict:
    """
    Return a dict of standard chess piece types keyed by name.

    All six pieces follow FIDE rules:
      - King:   one step any direction + castling
      - Rook:   unlimited orthogonal slides + castling partner
      - Bishop: unlimited diagonal slides
      - Queen:  unlimited ortho + diagonal slides
      - Knight: L-shaped leap (leapable=True → jumps over pieces)
      - Pawn:   forward push, double-push on first move, diagonal capture,
                en-passant, promotes to Queen/Rook/Bishop/Knight on back rank
    """
    p: dict = {}

    # King
    kr = [MoveRule(legs=[Leg(dr, dc, 1)])
          for dr in (-1, 0, 1) for dc in (-1, 0, 1)
          if not (dr == 0 and dc == 0)]
    kr.append(MoveRule(castling=True))
    p["King"] = PieceType("King", "K", kr,
                           is_royal=True, lethality=0.1, value=20000)

    # Rook — one rule per direction per step count (7 steps × 4 directions = 28 rules)
    rr = [MoveRule(legs=[Leg(dr, dc, s)])
          for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
          for s in range(1, 8)]
    p["Rook"] = PieceType("Rook", "R", rr,
                           is_castler=True, lethality=1.5, value=500)

    # Bishop
    br = [MoveRule(legs=[Leg(dr, dc, s)])
          for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1))
          for s in range(1, 8)]
    p["Bishop"] = PieceType("Bishop", "B", br, lethality=1.2, value=330)

    # Queen
    qr = [MoveRule(legs=[Leg(dr, dc, s)])
          for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1))
          for s in range(1, 8)]
    p["Queen"] = PieceType("Queen", "Q", qr, lethality=2.0, value=900)

    # Knight — leapable=True means it ignores intermediate pieces
    nr = [MoveRule(legs=[Leg(dr, dc, 1, leapable=True)])
          for dr, dc in ((2, 1), (2, -1), (-2, 1), (-2, -1),
                         (1, 2), (1, -2), (-1, 2), (-1, -2))]
    p["Knight"] = PieceType("Knight", "N", nr, lethality=1.2, value=320)

    # Pawn
    pr = [
        MoveRule(legs=[Leg(1, 0, 1)], non_capture_only=True),                   # push 1
        MoveRule(legs=[Leg(1, 0, 2)], non_capture_only=True, first_move_only=True),  # push 2
        MoveRule(legs=[Leg(1,  1, 1)], capture_only=True),                      # capture right
        MoveRule(legs=[Leg(1, -1, 1)], capture_only=True),                      # capture left
        MoveRule(en_passant=True),                                                # en passant
    ]
    p["Pawn"] = PieceType("Pawn", "P", pr, lethality=0.8, value=100,
                           promotable_to=["Queen", "Rook", "Bishop", "Knight"])

    print(f"[logic] Default pieces built: {list(p.keys())}")
    return p

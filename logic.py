"""logic.py — Fairy Chess Engine v3 (full rules + draw detection)"""

import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

@dataclass
class Leg:
    dx: int; dy: int; steps: int = 1; leapable: bool = False
    def to_dict(self): return {"dx":self.dx,"dy":self.dy,"steps":self.steps,"leapable":self.leapable}
    @staticmethod
    def from_dict(d): return Leg(d["dx"],d["dy"],d.get("steps",1),d.get("leapable",False))

@dataclass
class MoveRule:
    legs: List[Leg] = field(default_factory=list)
    capture_only: bool = False
    non_capture_only: bool = False
    first_move_only: bool = False
    n_moves_first: int = 1
    capture_filter: Optional[str] = None
    castling: bool = False
    en_passant: bool = False
    def to_dict(self):
        return {"legs":[l.to_dict() for l in self.legs],"capture_only":self.capture_only,
                "non_capture_only":self.non_capture_only,"first_move_only":self.first_move_only,
                "n_moves_first":self.n_moves_first,"capture_filter":self.capture_filter,
                "castling":self.castling,"en_passant":self.en_passant}
    @staticmethod
    def from_dict(d):
        r=MoveRule(); r.legs=[Leg.from_dict(l) for l in d.get("legs",[])]
        r.capture_only=d.get("capture_only",False); r.non_capture_only=d.get("non_capture_only",False)
        r.first_move_only=d.get("first_move_only",False); r.n_moves_first=d.get("n_moves_first",1)
        r.capture_filter=d.get("capture_filter",None); r.castling=d.get("castling",False)
        r.en_passant=d.get("en_passant",False); return r

@dataclass
class PieceType:
    name: str; symbol: str
    rules: List[MoveRule] = field(default_factory=list)
    is_royal: bool = False; is_castler: bool = False
    lethality: float = 1.0; promotable_to: List[str] = field(default_factory=list)
    def to_dict(self):
        return {"name":self.name,"symbol":self.symbol,"rules":[r.to_dict() for r in self.rules],
                "is_royal":self.is_royal,"is_castler":self.is_castler,
                "lethality":self.lethality,"promotable_to":self.promotable_to}
    @staticmethod
    def from_dict(d):
        pt=PieceType(name=d["name"],symbol=d.get("symbol","?"),is_royal=d.get("is_royal",False),
                     is_castler=d.get("is_castler",False),lethality=d.get("lethality",1.0),
                     promotable_to=d.get("promotable_to",[]))
        pt.rules=[MoveRule.from_dict(r) for r in d.get("rules",[])]; return pt

class Piece:
    _id=0
    def __init__(self,pt,owner,row,col):
        Piece._id+=1; self.uid=Piece._id
        self.piece_type=pt; self.owner=owner; self.row=row; self.col=col; self.has_moved=False
    def __repr__(self): return f"Piece({self.piece_type.symbol}{'wb'[self.owner]}@({self.row},{self.col}))"
    def clone(self):
        p=Piece.__new__(Piece); p.uid=self.uid; p.piece_type=self.piece_type
        p.owner=self.owner; p.row=self.row; p.col=self.col; p.has_moved=self.has_moved; return p

class Board:
    def __init__(self,rows=8,cols=8):
        self.rows=rows; self.cols=cols
        self.grid=[[None]*cols for _ in range(rows)]
        self.current_player=0; self.move_history=[]
        self.en_passant_target=None; self.halfmove_clock=0
        # For repetition detection: position hash → count
        self._position_counts: Dict[str,int] = {}

    def in_bounds(self,r,c): return 0<=r<self.rows and 0<=c<self.cols
    def place(self,p): self.grid[p.row][p.col]=p
    def get(self,r,c): return self.grid[r][c] if self.in_bounds(r,c) else None
    def all_pieces(self,owner=None):
        return [p for row in self.grid for p in row if p and (owner is None or p.owner==owner)]

    def position_key(self):
        """Compact string key of board position for repetition detection."""
        parts=[]
        for r in range(self.rows):
            for c in range(self.cols):
                p=self.grid[r][c]
                if p: parts.append(f"{r}{c}{p.piece_type.symbol}{p.owner}")
        return f"{''.join(parts)}/{self.current_player}/{self.en_passant_target}"

    def clone(self):
        b=Board.__new__(Board); b.rows=self.rows; b.cols=self.cols
        b.grid=[[None]*self.cols for _ in range(self.rows)]
        for r in range(self.rows):
            for c in range(self.cols):
                p=self.grid[r][c]
                if p: b.grid[r][c]=p.clone()
        b.current_player=self.current_player; b.move_history=list(self.move_history)
        b.en_passant_target=self.en_passant_target; b.halfmove_clock=self.halfmove_clock
        b._position_counts=dict(self._position_counts); return b

    def apply_move(self,move):
        b=self.clone(); fr,fc=move["from_pos"]; tr,tc=move["to_pos"]
        piece=b.grid[fr][fc]; b.en_passant_target=None
        is_capture=move.get("captured_uid") is not None
        is_pawn=piece.piece_type.symbol in ("P","p")
        if move.get("en_passant_capture"):
            ep_r,ep_c=move["en_passant_capture"]; b.grid[ep_r][ep_c]=None
        elif is_capture:
            b.grid[tr][tc]=None
        b.grid[fr][fc]=None; piece.row,piece.col=tr,tc; b.grid[tr][tc]=piece
        if move.get("double_push"):
            ep_row=(fr+tr)//2; b.en_passant_target=(ep_row,tc)
        if move.get("promotion_type"):
            piece.piece_type=move["promotion_type"]
        if move.get("castling"):
            ci=move["castling"]; cr,cc=ci["from_pos"]; castler=b.grid[cr][cc]
            if castler:
                b.grid[cr][cc]=None; castler.row,castler.col=ci["to_pos"][0],ci["to_pos"][1]
                castler.has_moved=True; b.grid[ci["to_pos"][0]][ci["to_pos"][1]]=castler
        piece.has_moved=True; b.current_player=1-b.current_player; b.move_history.append(move)
        # Halfmove clock (for 50-move rule)
        if is_capture or is_pawn: b.halfmove_clock=0
        else: b.halfmove_clock=self.halfmove_clock+1
        # Track position counts
        key=b.position_key(); b._position_counts[key]=b._position_counts.get(key,0)+1
        return b

    def find_king(self,owner):
        for p in self.all_pieces(owner):
            if p.piece_type.is_royal: return p
        return None

    # Draw detection
    def is_fifty_move_draw(self): return self.halfmove_clock>=100
    def is_threefold_repetition(self):
        return any(v>=3 for v in self._position_counts.values())
    def is_insufficient_material(self):
        """True for K vs K, K+B vs K, K+N vs K."""
        pieces=[p for row in self.grid for p in row if p]
        if len(pieces)==2: return True  # K vs K
        if len(pieces)==3:
            non_kings=[p for p in pieces if not p.piece_type.is_royal]
            if non_kings and non_kings[0].piece_type.name in ("Bishop","Knight"): return True
        return False

class MoveGenerator:
    def get_moves(self,piece,board,legal_only=False):
        moves=[]
        for rule in piece.piece_type.rules:
            if rule.first_move_only and piece.has_moved: continue
            if rule.castling: moves+=self._castling(piece,board); continue
            if rule.en_passant: moves+=self._en_passant(piece,board); continue
            max_rep=rule.n_moves_first if not piece.has_moved else 1
            for rep in range(1,max_rep+1):
                moves+=self._trace(piece,board,rule,rep)
        if legal_only:
            moves=[m for m in moves if not self._in_check_after(m,board,piece.owner)]
        return moves

    def _trace(self,piece,board,rule,reps=1):
        all_legs=rule.legs*reps
        if not all_legs: return []
        flip=-1 if piece.owner==1 else 1
        r,c=piece.row,piece.col; blocked=False
        for leg in all_legs:
            dx=leg.dx*flip; dy=leg.dy*flip
            for step in range(leg.steps):
                nr,nc=r+dx,c+dy
                if not board.in_bounds(nr,nc): blocked=True; break
                is_last=(leg is all_legs[-1]) and (step==leg.steps-1)
                if not is_last and board.get(nr,nc) is not None and not leg.leapable:
                    blocked=True; break
                r,c=nr,nc
            if blocked: break
        if blocked: return []
        target=board.get(r,c)
        if target and target.owner==piece.owner: return []
        if rule.capture_only and not target: return []
        if rule.non_capture_only and target: return []
        move={"piece_uid":piece.uid,"from_pos":(piece.row,piece.col),"to_pos":(r,c),
              "captured_uid":target.uid if target else None}
        if abs(r-piece.row)==2 and piece.col==c and piece.piece_type.symbol in("P","p") and not piece.has_moved:
            move["double_push"]=True
        promo_row=7 if piece.owner==0 else 0
        if r==promo_row and piece.piece_type.promotable_to:
            move["needs_promotion"]=True; move["promotion_options"]=piece.piece_type.promotable_to
        return [move]

    def _en_passant(self,piece,board):
        if board.en_passant_target is None: return []
        ep_r,ep_c=board.en_passant_target; flip=-1 if piece.owner==1 else 1
        pr,pc=piece.row,piece.col
        if abs(pc-ep_c)==1 and pr+flip==ep_r:
            cap=board.get(pr,ep_c)
            return [{"piece_uid":piece.uid,"from_pos":(pr,pc),"to_pos":(ep_r,ep_c),
                     "captured_uid":cap.uid if cap else None,"en_passant_capture":(pr,ep_c)}]
        return []

    def _castling(self,king,board):
        if king.has_moved or self._is_in_check(board,king.owner): return []
        moves=[]; kr,kc=king.row,king.col
        for castler in board.all_pieces(king.owner):
            if not castler.piece_type.is_castler or castler.has_moved: continue
            cr,cc=castler.row,castler.col
            same_row=kr==cr; same_col=kc==cc
            if not same_row and not same_col: continue
            path_clear=True
            if same_row:
                step=1 if cc>kc else -1
                for tc in range(kc+step,cc,step):
                    if board.get(kr,tc): path_clear=False; break
                if not path_clear: continue
                king_to=(kr,kc+2*step); castler_to=(kr,kc+step)
                if self._sq_attacked(board,(kr,kc+step),1-king.owner): continue
            else:
                step=1 if cr>kr else -1
                for tr in range(kr+step,cr,step):
                    if board.get(tr,kc): path_clear=False; break
                if not path_clear: continue
                king_to=(kr+2*step,kc); castler_to=(kr+step,kc)
                if self._sq_attacked(board,(kr+step,kc),1-king.owner): continue
            if not board.in_bounds(*king_to) or not board.in_bounds(*castler_to): continue
            if self._sq_attacked(board,king_to,1-king.owner): continue
            moves.append({"piece_uid":king.uid,"from_pos":(kr,kc),"to_pos":king_to,
                          "captured_uid":None,"castling":{"castler_uid":castler.uid,
                          "from_pos":(cr,cc),"to_pos":castler_to}})
        return moves

    def _in_check_after(self,move,board,owner):
        return self._is_in_check(board.apply_move(move),owner)

    def _is_in_check(self,board,owner):
        king=board.find_king(owner)
        return True if king is None else self._sq_attacked(board,(king.row,king.col),1-owner)

    def _sq_attacked(self,board,sq,by_owner):
        for p in board.all_pieces(by_owner):
            for rule in p.piece_type.rules:
                if rule.castling or rule.en_passant or rule.non_capture_only: continue
                for m in self._trace(p,board,rule,1):
                    if m["to_pos"]==sq: return True
        return False

    def all_moves(self,board,owner,legal_only=True):
        moves=[]
        for p in board.all_pieces(owner): moves+=self.get_moves(p,board,legal_only)
        return moves

    def is_checkmate(self,board,owner):
        return self._is_in_check(board,owner) and not self.all_moves(board,owner)
    def is_stalemate(self,board,owner):
        return not self._is_in_check(board,owner) and not self.all_moves(board,owner)
    def is_in_check(self,board,owner): return self._is_in_check(board,owner)
    def is_royal_alive(self,board,owner): return board.find_king(owner) is not None

    def game_result(self,board):
        """Returns: 'checkmate', 'stalemate', '50move', 'repetition', 'material', or None"""
        cp=board.current_player
        if self.is_checkmate(board,cp): return "checkmate"
        if self.is_stalemate(board,cp): return "stalemate"
        if board.is_fifty_move_draw(): return "50move"
        if board.is_threefold_repetition(): return "repetition"
        if board.is_insufficient_material(): return "material"
        return None

def save_piece_types(piece_types,path):
    with open(path,"w") as f: json.dump({n:pt.to_dict() for n,pt in piece_types.items()},f,indent=2)

def load_piece_types(path):
    with open(path) as f: data=json.load(f)
    return {n:PieceType.from_dict(d) for n,d in data.items()}

def parse_segment_string(seg):
    legs=[]
    for part in seg.split(";"):
        t=[x.strip() for x in part.strip().split(",")]
        if len(t)<2: continue
        dx,dy=int(t[0]),int(t[1]); steps=int(t[2]) if len(t)>2 else 1
        leap=t[3].lower()=="true" if len(t)>3 else False
        legs.append(Leg(dx,dy,steps,leap))
    return legs

def build_default_pieces():
    p={}
    kr=[MoveRule(legs=[Leg(dr,dc,1)]) for dr in[-1,0,1] for dc in[-1,0,1] if not(dr==0 and dc==0)]
    kr.append(MoveRule(castling=True))
    p["King"]=PieceType("King","K",kr,is_royal=True,lethality=0.1)
    rr=[MoveRule(legs=[Leg(dr,dc,s)]) for dr,dc in[(1,0),(-1,0),(0,1),(0,-1)] for s in range(1,8)]
    p["Rook"]=PieceType("Rook","R",rr,is_castler=True,lethality=1.5)
    br=[MoveRule(legs=[Leg(dr,dc,s)]) for dr,dc in[(1,1),(1,-1),(-1,1),(-1,-1)] for s in range(1,8)]
    p["Bishop"]=PieceType("Bishop","B",br,lethality=1.2)
    qr=[MoveRule(legs=[Leg(dr,dc,s)]) for dr,dc in[(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)] for s in range(1,8)]
    p["Queen"]=PieceType("Queen","Q",qr,lethality=2.0)
    nr=[MoveRule(legs=[Leg(dr,dc,1,True)]) for dr,dc in[(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]]
    p["Knight"]=PieceType("Knight","N",nr,lethality=1.2)
    pr=[MoveRule(legs=[Leg(1,0,1)],non_capture_only=True),
        MoveRule(legs=[Leg(1,0,2)],non_capture_only=True,first_move_only=True),
        MoveRule(legs=[Leg(1,1,1)],capture_only=True),
        MoveRule(legs=[Leg(1,-1,1)],capture_only=True),
        MoveRule(en_passant=True)]
    p["Pawn"]=PieceType("Pawn","P",pr,lethality=0.8,promotable_to=["Queen","Rook","Bishop","Knight"])
    return p

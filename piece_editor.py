"""
piece_editor.py  -  Fairy Chess Piece Editor  v3  (production)
===============================================================
All UI is native Tkinter (no pygame).
Piece icons loaded via Pillow from the active pack or default assets/chessmat.

New in v3:
  - Move grid: better colors, larger coordinates, cleaner contrast
  - Icon picker: real PNG icons from active pack (Pillow), 6x2 grid
  - Icon picker used in left panel (shows actual piece images, not colored boxes)
  - Pack-aware: reads active pack from packs.json just like gui.py does
"""

import os, json
import tkinter as tk
from tkinter import ttk, messagebox

from logic import PieceType, MoveRule, Leg, build_default_pieces

print("[DEBUG editor] piece_editor.py v3 loaded")

# ── Colour palette (matches gui.py exactly) ───────────────────────────────────
BG    = "#0D0D13"
PANEL = "#12121C"
SURF  = "#1A1A26"
SURF2 = "#202030"
BORD  = "#2A2A3E"
TXT   = "#D0D0E0"
DIM   = "#5F5F76"
RED   = "#BE3232"
GOLD  = "#CDA537"

# Move cell display modes
M_EMPTY = 0
M_MOVE  = 1   # move + capture
M_CAP   = 2   # capture only
M_NOCAP = 3   # no-capture only
M_HEX   = {M_MOVE: "#41BE55", M_CAP: "#D24141", M_NOCAP: "#4173D2"}

GRID_N  = 9
GRID_CR = GRID_N // 2   # centre cell index (= 4)

SYM_FILE = {
    "K": "king", "Q": "queen", "R": "rook",
    "B": "bishop", "N": "knight", "P": "pawn",
}
ALL_SYMS = list(SYM_FILE.keys())


def _font(size=10, bold=False, mono=False):
    if mono:
        return ("DejaVu Sans Mono", size)
    return ("Poppins", size, "bold") if bold else ("Poppins", size)


# ── Pack-aware icon loading ───────────────────────────────────────────────────
_PACKS_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs.json")


def _get_active_pack_root():
    """Return folder path for the currently active pack (or default)."""
    if os.path.isfile(_PACKS_CFG):
        try:
            with open(_PACKS_CFG) as f:
                cfg = json.load(f)
            active = cfg.get("__active__", "")
            if active and active in cfg:
                path = cfg[active]
                if os.path.isdir(path):
                    return path
        except Exception as e:
            print(f"[DEBUG editor] packs.json error: {e}")
    here = os.path.dirname(os.path.abspath(__file__))
    for base in [here, os.getcwd(), os.path.join(here, "..")]:
        p = os.path.join(base, "assets", "chessmat")
        if os.path.isdir(p):
            return p
    return None


def load_editor_icons(size=40):
    """
    Load piece PNGs as tk.PhotoImage for the editor UI.
    Returns {(symbol, owner): PhotoImage} — keeps refs alive in the dict.
    Falls back silently if Pillow or files are missing.
    """
    imgs = {}
    root = _get_active_pack_root()
    if not root:
        print("[DEBUG editor] no pack root — icon fallback")
        return imgs
    try:
        from PIL import Image as PilImg, ImageTk as PilTk
    except ImportError:
        print("[DEBUG editor] Pillow missing — no icons in editor")
        return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path):
                print(f"[DEBUG editor] missing: {path}")
                continue
            try:
                img = PilImg.open(path).convert("RGBA").resize(
                    (size, size), PilImg.LANCZOS)
                imgs[(sym, owner)] = PilTk.PhotoImage(img)
            except Exception as e:
                print(f"[DEBUG editor] icon error {path}: {e}")
    print(f"[DEBUG editor] loaded {len(imgs)}/12 icons @ {size}px")
    return imgs


# ─────────────────────────────────────────────────────────────────────────────
# Move Grid Canvas  — 9×9 interactive movement pattern editor
# ─────────────────────────────────────────────────────────────────────────────
class MoveGridCanvas(tk.Canvas):
    """
    9×9 clickable grid for editing piece movement patterns.

    Interactions:
      Left-click  : toggle EMPTY <-> MOVE
      Right-click : cycle EMPTY -> MOVE -> CAPTURE_ONLY -> NO_CAPTURE -> EMPTY
      Middle-click: toggle leap flag on that cell

    Visual improvements in v3:
      - Larger coordinate labels (more visible, contrast-matched to square colour)
      - Cleaner board colours inspired by lichess dark board
      - Origin diamond is gold and larger
      - Leap badge is clearly labelled
    """
    CELL = 52
    PAD  = 2

    def __init__(self, master, **kw):
        sz = GRID_N * self.CELL + self.PAD * 2
        super().__init__(master, width=sz, height=sz,
                         bg="#0C0C18", highlightthickness=1,
                         highlightbackground=BORD, **kw)
        self.cells       = [[M_EMPTY] * GRID_N for _ in range(GRID_N)]
        self.leap        = [[False]   * GRID_N for _ in range(GRID_N)]
        self.sliding     = False
        self._piece_icon = None   # tk.PhotoImage shown in centre cell
        self.bind("<Button-1>", self._on_left)
        self.bind("<Button-3>", self._on_right)
        self.bind("<Button-2>", self._on_mid)
        self._redraw()

    def set_piece_icon(self, photo_image):
        """
        Show piece icon in the centre cell.
        photo_image: tk.PhotoImage sized to ~CELL px, or None.
        Called by editor when the user selects a different piece symbol.
        """
        self._piece_icon = photo_image
        self._redraw()
        print(f"[DEBUG editor] move grid icon = {photo_image is not None}")

    def _rc(self, event):
        c = (event.x - self.PAD) // self.CELL
        r = (event.y - self.PAD) // self.CELL
        return (r, c) if (0 <= r < GRID_N and 0 <= c < GRID_N) else (None, None)

    def _on_left(self, event):
        r, c = self._rc(event)
        if r is None or (r == GRID_CR and c == GRID_CR): return
        self.cells[r][c] = M_EMPTY if self.cells[r][c] else M_MOVE
        self._redraw()

    def _on_right(self, event):
        r, c = self._rc(event)
        if r is None or (r == GRID_CR and c == GRID_CR): return
        self.cells[r][c] = (self.cells[r][c] + 1) % 4
        self._redraw()

    def _on_mid(self, event):
        r, c = self._rc(event)
        if r is None or (r == GRID_CR and c == GRID_CR): return
        self.leap[r][c] = not self.leap[r][c]
        self._redraw()

    def _redraw(self):
        """
        Redraw the 9x9 movement grid.
        v4 improvements:
          - Vivid chess-board colours (rich green / warm cream like lichess)
          - Coordinate labels on all 4 edges (file offsets bottom+top, rank offsets left+right)
          - Centre square shows the current piece icon if available (set via set_piece_icon())
          - Leap badge is clearly visible with gold background
        """
        self.delete("cell")
        C, P = self.CELL, self.PAD

        # Vivid chess colours matching the board in gui.py
        SQ_L = "#D4D9B2"   # warm light square
        SQ_D = "#4A7A40"   # rich green dark square
        SQ_C = "#1A1A30"   # centre square (piece origin)

        for r in range(GRID_N):
            for c in range(GRID_N):
                x1 = P + c * C; y1 = P + r * C
                x2 = x1 + C - 1; y2 = y1 + C - 1
                cx = x1 + C // 2; cy = y1 + C // 2
                is_cen = (r == GRID_CR and c == GRID_CR)

                # Square colour — vivid alternating + special centre
                if is_cen:
                    bg = SQ_C
                elif (r + c) % 2 == 0:
                    bg = SQ_L
                else:
                    bg = SQ_D
                self.create_rectangle(x1, y1, x2, y2, fill=bg, outline="#222230", tags="cell")

                if is_cen:
                    # Show piece icon if available, else gold diamond
                    icon = getattr(self, "_piece_icon", None)
                    if icon:
                        self.create_image(cx, cy, image=icon, anchor="center", tags="cell")
                    else:
                        d = 11
                        pts = [cx, cy-d, cx+d, cy, cx, cy+d, cx-d, cy]
                        self.create_polygon(pts, fill=GOLD, outline="#9A7A18", width=1, tags="cell")
                    continue

                mode = self.cells[r][c]
                if mode != M_EMPTY:
                    col = M_HEX[mode]
                    if mode == M_MOVE:
                        rr = C // 4
                        self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr,
                                         fill=col, outline="", tags="cell")
                    else:
                        rr = C // 4 + 2
                        self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr,
                                         fill="", outline=col, width=3, tags="cell")
                    # Leap badge — gold pill in top-left corner
                    if self.leap[r][c]:
                        self.create_rectangle(x1+2, y1+2, x1+18, y1+14,
                                              fill="#C8A820", outline="#907814", tags="cell")
                        self.create_text(x1+10, y1+8, text="L", fill="#0A0808",
                                         font=_font(6, bold=True), tags="cell")

                # ── Coordinate labels on edges ────────────────────────────────
                # These show the movement offset from origin (centre)
                light_sq = (r + c) % 2 == 0
                coord_col = SQ_D if light_sq else SQ_L  # contrasting colour

                # Top row: column file offsets (+dx label)
                if r == 0:
                    off = c - GRID_CR
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(cx, y1+7, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True), tags="cell")

                # Bottom row: file offsets (repeated for easy reading)
                if r == GRID_N - 1:
                    off = c - GRID_CR
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(cx, y2-6, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True), tags="cell")

                # Left column: rank offsets (+dy label)
                if c == 0:
                    off = GRID_CR - r   # positive = forward (up)
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(x1+8, cy, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True), tags="cell")

                # Right column: rank offsets (repeated)
                if c == GRID_N - 1:
                    off = GRID_CR - r
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(x2-7, cy, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True), tags="cell")

    def clear(self):
        self.cells = [[M_EMPTY]*GRID_N for _ in range(GRID_N)]
        self.leap  = [[False  ]*GRID_N for _ in range(GRID_N)]
        self._redraw()

    def load_piece(self, pt):
        """Load 1-leg rules from a PieceType into the grid."""
        self.clear()
        for rule in pt.rules:
            if rule.castling or rule.en_passant: continue
            if len(rule.legs) == 1 and rule.legs[0].steps == 1:
                leg = rule.legs[0]
                r   = GRID_CR - leg.dx
                c   = GRID_CR + leg.dy
                if 0 <= r < GRID_N and 0 <= c < GRID_N and not (r == GRID_CR and c == GRID_CR):
                    mode = M_CAP if rule.capture_only else (
                           M_NOCAP if rule.non_capture_only else M_MOVE)
                    self.cells[r][c] = mode
                    self.leap[r][c]  = leg.leapable
        self._redraw()
        print("[DEBUG editor] grid loaded from piece")

    def to_rules(self):
        """Convert grid state to a list of MoveRule objects."""
        rules = []
        for r in range(GRID_N):
            for c in range(GRID_N):
                mode = self.cells[r][c]
                if mode == M_EMPTY or (r == GRID_CR and c == GRID_CR): continue
                dr   = GRID_CR - r
                dc   = c - GRID_CR
                leap = self.leap[r][c]
                steps = 7 if self.sliding else 1
                for s in range(1, steps + 1):
                    rules.append(MoveRule(
                        legs=[Leg(dr, dc, s, leap)],
                        capture_only=(mode == M_CAP),
                        non_capture_only=(mode == M_NOCAP),
                    ))
        return rules


# ─────────────────────────────────────────────────────────────────────────────
# Icon Picker Canvas — 6×2 grid of real piece images
# ─────────────────────────────────────────────────────────────────────────────
class IconPickerCanvas(tk.Canvas):
    """
    6 columns (symbols) × 2 rows (white / black).
    Shows actual PNG icons if available; falls back to coloured ovals.
    Click to select a symbol.
    """
    ICON = 46
    GAP  = 5

    def __init__(self, master, tk_icons, on_select=None, **kw):
        cols = len(ALL_SYMS)
        rows = 2
        w = cols * (self.ICON + self.GAP) + self.GAP
        h = rows * (self.ICON + self.GAP) + self.GAP
        super().__init__(master, width=w, height=h,
                         bg=SURF, highlightthickness=0, **kw)
        self.tk_icons  = tk_icons
        self.on_select = on_select
        self.selected  = "Q"
        self.bind("<Button-1>", self._on_click)
        self._redraw()
        print("[DEBUG editor] IconPickerCanvas created")

    def _cell_xy(self, owner, idx):
        x = self.GAP + idx * (self.ICON + self.GAP)
        y = self.GAP + owner * (self.ICON + self.GAP)
        return x, y

    def _on_click(self, event):
        for owner in range(2):
            for i, sym in enumerate(ALL_SYMS):
                x, y = self._cell_xy(owner, i)
                if x <= event.x < x + self.ICON and y <= event.y < y + self.ICON:
                    self.selected = sym
                    self._redraw()
                    if self.on_select:
                        self.on_select(sym)
                    print(f"[DEBUG editor] icon selected: {sym} owner={owner}")
                    return

    def _redraw(self):
        self.delete("all")
        for owner in range(2):
            for i, sym in enumerate(ALL_SYMS):
                x, y = self._cell_xy(owner, i)
                sel  = (sym == self.selected)
                bg   = "#3A2808" if sel else SURF2
                brd  = GOLD     if sel else BORD
                self.create_rectangle(x, y, x + self.ICON, y + self.ICON,
                                      fill=bg, outline=brd, width=2)
                # Owner label in corner (tiny, low contrast)
                olbl = "W" if owner == 0 else "B"
                self.create_text(x + self.ICON - 3, y + 3, text=olbl,
                                 anchor="ne", fill=DIM, font=_font(6))

                img = self.tk_icons.get((sym, owner))
                if img:
                    self.create_image(x + self.ICON//2, y + self.ICON//2,
                                      image=img, anchor="center")
                else:
                    # Fallback: coloured oval (no text, no unicode)
                    pad = 8
                    fc  = "#D0CCC0" if owner == 0 else "#302C28"
                    self.create_oval(x+pad, y+pad,
                                     x+self.ICON-pad, y+self.ICON-pad,
                                     fill=fc, outline="")


# ─────────────────────────────────────────────────────────────────────────────
# Multi-leg Rule Builder
# ─────────────────────────────────────────────────────────────────────────────
class MultilegFrame(tk.Frame):
    """
    Visual builder for multi-leg movement rules.
    User picks direction from a 3×3 compass, sets steps, clicks Add Leg,
    repeats for each leg, then Finish Rule to commit.
    """

    def __init__(self, master, accent, **kw):
        super().__init__(master, bg=PANEL, **kw)
        self.accent = accent
        self.rules: list = []           # completed rules (list of Leg lists)
        self._cur_legs: list = []       # legs being assembled
        self._dir_sel = (1, 0)          # selected (dx, dy)
        self._build()

    def _build(self):
        BS = dict(bg=SURF2, fg=TXT, relief="flat", font=_font(9),
                  padx=6, pady=3, cursor="hand2",
                  activebackground=SURF, activeforeground=TXT, bd=0)

        tk.Label(self, text="Multi-leg Rules", bg=PANEL, fg=self.accent,
                 font=_font(11, bold=True)).pack(anchor="w", pady=(8, 3))
        tk.Label(self, bg=PANEL, fg=DIM, font=_font(8),
                 text="Build compound moves: pick direction, add legs, finish rule."
                 ).pack(anchor="w", pady=(0, 8))

        # ── Builder row ───────────────────────────────────────────────────────
        builder = tk.Frame(self, bg=PANEL)
        builder.pack(fill="x", pady=(0, 8))

        # Direction 3×3 compass
        dir_f = tk.LabelFrame(builder, text="Direction", bg=PANEL, fg=DIM,
                              font=_font(8), bd=1, relief="flat",
                              highlightthickness=1, highlightbackground=BORD)
        dir_f.pack(side="left", padx=(0, 10))

        dir_labels = [
            [(-1,-1), (-1,0), (-1,1)],
            [( 0,-1), None,   ( 0,1)],
            [( 1,-1), ( 1,0), ( 1,1)],
        ]
        dir_arrows = [
            ["NW","N","NE"],
            ["W", "", "E" ],
            ["SW","S","SE"],
        ]
        self._dir_btns = {}
        for gr in range(3):
            for gc in range(3):
                dd  = dir_labels[gr][gc]
                lbl = dir_arrows[gr][gc]
                if dd is None:
                    tk.Frame(dir_f, width=36, height=28, bg=BG).grid(
                        row=gr, column=gc, padx=2, pady=2)
                    continue
                b = tk.Button(dir_f, text=lbl, width=3,
                              bg=SURF2, fg=TXT, relief="flat",
                              font=_font(9, bold=True), cursor="hand2", bd=0, pady=2,
                              activebackground=SURF, activeforeground=TXT,
                              command=lambda d=dd: self._select_dir(d))
                b.grid(row=gr, column=gc, padx=2, pady=2)
                self._dir_btns[dd] = b
        self._select_dir((-1, 0))  # default: forward

        # Steps + leap
        opts_f = tk.Frame(builder, bg=PANEL)
        opts_f.pack(side="left", padx=(0, 10))
        tk.Label(opts_f, text="Steps", bg=PANEL, fg=DIM, font=_font(8)).pack(anchor="w")
        self._steps_var = tk.IntVar(value=1)
        tk.Spinbox(opts_f, from_=1, to=8, textvariable=self._steps_var,
                   width=3, bg=SURF2, fg=TXT, insertbackground=TXT,
                   relief="flat", font=_font(10), buttonbackground=SURF2,
                   highlightthickness=0).pack(anchor="w", pady=(2, 6))
        self._leap_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts_f, text="Leapable", variable=self._leap_var,
                       bg=PANEL, fg=TXT, selectcolor=SURF2,
                       activebackground=PANEL, font=_font(9)).pack(anchor="w")

        # Add / Finish / Clear buttons
        btn_col = tk.Frame(builder, bg=PANEL)
        btn_col.pack(side="left", anchor="n")
        for label, cmd, clr, fclr in [
            ("Add Leg",    self._add_leg,      "#142A1C", "#70D890"),
            ("Finish Rule",self._finish_rule,  "#0E1C3A", "#70A8E0"),
            ("Clear",      self._clear_cur,    "#2E0E0E", "#E08888"),
        ]:
            tk.Button(btn_col, text=label, width=10, command=cmd,
                      bg=clr, fg=fclr, relief="flat", font=_font(9),
                      cursor="hand2", pady=4, bd=0,
                      activebackground=SURF, activeforeground=TXT).pack(pady=(0, 3))

        # Capture / no-capture flags for whole rule
        flag_f = tk.Frame(self, bg=PANEL)
        flag_f.pack(fill="x", pady=(0, 6))
        self._cap_var   = tk.BooleanVar()
        self._nocap_var = tk.BooleanVar()
        tk.Checkbutton(flag_f, text="Capture only", variable=self._cap_var,
                       bg=PANEL, fg=TXT, selectcolor=SURF2,
                       activebackground=PANEL, font=_font(9)).pack(side="left", padx=(0, 10))
        tk.Checkbutton(flag_f, text="No-capture", variable=self._nocap_var,
                       bg=PANEL, fg=TXT, selectcolor=SURF2,
                       activebackground=PANEL, font=_font(9)).pack(side="left")

        # Current-rule preview
        tk.Label(self, text="Current rule (legs so far):", bg=PANEL, fg=DIM,
                 font=_font(8)).pack(anchor="w")
        self._cur_frame = tk.Frame(self, bg=SURF, bd=0)
        self._cur_frame.pack(fill="x", pady=(2, 6))
        self._refresh_cur()

        # Completed rules list
        tk.Frame(self, bg=BORD, height=1).pack(fill="x", pady=4)
        tk.Label(self, text="Completed multi-leg rules:", bg=PANEL, fg=DIM,
                 font=_font(8)).pack(anchor="w")
        self._rules_frame = tk.Frame(self, bg=PANEL)
        self._rules_frame.pack(fill="both", expand=True)
        self._refresh_rules()

    def _select_dir(self, dd):
        self._dir_sel = dd
        for d, btn in self._dir_btns.items():
            btn.config(bg=self.accent if d == dd else SURF2,
                       fg="#0A0A0A"   if d == dd else TXT)
        print(f"[DEBUG editor] dir={dd}")

    def _add_leg(self):
        dx, dy   = self._dir_sel
        steps    = max(1, self._steps_var.get())
        leapable = self._leap_var.get()
        self._cur_legs.append(Leg(dx, dy, steps, leapable))
        self._refresh_cur()
        print(f"[DEBUG editor] leg added: dx={dx} dy={dy} steps={steps} leap={leapable}")

    def _finish_rule(self):
        if not self._cur_legs:
            messagebox.showinfo("No legs", "Add at least one leg first.", parent=self)
            return
        self.rules.append(list(self._cur_legs))
        self._cur_legs = []
        self._cap_var.set(False)
        self._nocap_var.set(False)
        self._refresh_cur()
        self._refresh_rules()
        print(f"[DEBUG editor] rule finished, total={len(self.rules)}")

    def _clear_cur(self):
        self._cur_legs = []
        self._refresh_cur()

    def _refresh_cur(self):
        for w in self._cur_frame.winfo_children():
            w.destroy()
        if not self._cur_legs:
            tk.Label(self._cur_frame, text="  (empty — add legs above)",
                     bg=SURF, fg=DIM, font=_font(9)).pack(anchor="w", padx=6, pady=5)
        else:
            parts = " -> ".join(
                f"({l.dx},{l.dy}) x{l.steps}{'[L]' if l.leapable else ''}"
                for l in self._cur_legs)
            tk.Label(self._cur_frame, text=f"  {parts}",
                     bg=SURF, fg=TXT, font=_font(9, mono=True)
                     ).pack(anchor="w", padx=6, pady=5)

    def _refresh_rules(self):
        for w in self._rules_frame.winfo_children():
            w.destroy()
        if not self.rules:
            tk.Label(self._rules_frame, text="  No completed rules yet.",
                     bg=PANEL, fg=DIM, font=_font(9)).pack(anchor="w")
            return
        for i, legs in enumerate(self.rules):
            row = tk.Frame(self._rules_frame, bg=SURF2)
            row.pack(fill="x", pady=2)
            parts = " -> ".join(
                f"({l.dx},{l.dy}) x{l.steps}{'[L]' if l.leapable else ''}" for l in legs)
            tk.Label(row, text=f"  {i+1}.  {parts}",
                     bg=SURF2, fg=TXT, font=_font(9, mono=True),
                     anchor="w").pack(side="left", fill="x", expand=True, padx=4)
            tk.Button(row, text="x",
                      command=lambda ix=i: self._del_rule(ix),
                      bg="#3A1414", fg="#E08080", relief="flat",
                      font=_font(9), padx=4, cursor="hand2", bd=0
                      ).pack(side="right", padx=4)

    def _del_rule(self, idx):
        if 0 <= idx < len(self.rules):
            self.rules.pop(idx)
            self._refresh_rules()

    def get_move_rules(self):
        """Return list of MoveRule from completed rules."""
        return [
            MoveRule(
                legs=legs,
                capture_only=self._cap_var.get(),
                non_capture_only=self._nocap_var.get(),
            )
            for legs in self.rules
        ]

    def set_from_rules(self, rules):
        """Populate from existing MoveRule list (for loading a piece)."""
        self.rules     = [list(r.legs) for r in rules if len(r.legs) > 1]
        self._cur_legs = []
        self._refresh_cur()
        self._refresh_rules()


# ─────────────────────────────────────────────────────────────────────────────
# Main Editor Window
# ─────────────────────────────────────────────────────────────────────────────
class EditorWindow(tk.Toplevel):
    """
    Full piece editor modal.
    on_save(piece_types_dict) called when user clicks Save Piece.
    """

    def __init__(self, master, piece_types, piece_images, accent, on_save=None):
        super().__init__(master)
        self.title("Piece Editor")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()

        self.piece_types = {k: v for k, v in piece_types.items()}
        self.accent      = accent
        self.on_save_cb  = on_save
        self._editing    = None

        # Load icons from active pack for this editor session
        self.tk_icons = load_editor_icons(40)

        # Apply ttk styles
        style = ttk.Style(self)
        style.theme_use("clam")
        for cls in ("TCombobox", "TEntry"):
            style.configure(cls, fieldbackground=SURF2, background=SURF2,
                            foreground=TXT, selectbackground=SURF2,
                            bordercolor=BORD)
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background=SURF2, foreground=DIM,
                        padding=[12, 6], font=_font(10))
        style.map("TNotebook.Tab",
                  background=[("selected", accent)],
                  foreground=[("selected", "#0A0A0A")])
        style.configure("TScrollbar", background=SURF2, troughcolor=SURF,
                        arrowcolor=DIM, bordercolor=SURF)

        self._build_ui()
        self._refresh_piece_list()

        if self.piece_types:
            first = list(self.piece_types.keys())[0]
            self._load_piece(first)
            self.piece_list.selection_set(0)

        # Centre on parent
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width()  - self.winfo_width())  // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")
        print("[DEBUG editor] EditorWindow opened")

    # ── Build layout ──────────────────────────────────────────────────────────
    def _build_ui(self):
        acc = self.accent
        ef  = dict(bg=SURF2, fg=TXT, insertbackground=TXT, relief="flat",
                   font=_font(11), bd=0, highlightthickness=1,
                   highlightbackground=BORD, highlightcolor=acc)
        bs  = dict(bg=SURF2, fg=TXT, relief="flat", font=_font(10),
                   padx=8, pady=4, cursor="hand2",
                   activebackground=SURF, activeforeground=TXT, bd=0)

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=PANEL, width=290)
        left.pack(side="left", fill="y", padx=(0, 1))
        left.pack_propagate(False)

        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # ── LEFT: piece list ──────────────────────────────────────────────────
        tk.Label(left, text="PIECES", bg=PANEL, fg=DIM, font=_font(9)
                 ).pack(anchor="w", padx=12, pady=(10, 2))

        lf = tk.Frame(left, bg=SURF)
        lf.pack(fill="x", padx=12, pady=(0, 4))
        scr = tk.Scrollbar(lf, orient="vertical")
        self.piece_list = tk.Listbox(
            lf, yscrollcommand=scr.set, height=7,
            bg=SURF, fg=TXT, selectbackground=SURF2, selectforeground=acc,
            font=_font(11), relief="flat", bd=0,
            activestyle="none", highlightthickness=0, exportselection=False)
        scr.config(command=self.piece_list.yview)
        scr.pack(side="right", fill="y")
        self.piece_list.pack(side="left", fill="both", expand=True)
        self.piece_list.bind("<<ListboxSelect>>", self._on_list_sel)

        br = tk.Frame(left, bg=PANEL)
        br.pack(fill="x", padx=12, pady=(0, 6))
        tk.Button(br, text="New Piece", command=self._new_piece,
                  **dict(bs, bg="#142A1A", fg="#70D890")
                  ).pack(side="left", expand=True, fill="x", padx=(0, 3))
        tk.Button(br, text="Delete", command=self._delete_piece,
                  **dict(bs, bg="#2E0E0E", fg="#E08080")
                  ).pack(side="left", expand=True, fill="x")

        tk.Frame(left, bg=BORD, height=1).pack(fill="x", padx=12, pady=4)

        # ── LEFT: details ─────────────────────────────────────────────────────
        tk.Label(left, text="DETAILS", bg=PANEL, fg=DIM, font=_font(9)
                 ).pack(anchor="w", padx=12, pady=(2, 4))

        tk.Label(left, text="Name", bg=PANEL, fg=TXT, font=_font(10)
                 ).pack(anchor="w", padx=12)
        self.name_var = tk.StringVar()
        tk.Entry(left, textvariable=self.name_var, **ef
                 ).pack(fill="x", padx=12, pady=(2, 6))

        tk.Label(left, text="Symbol  (1 character)", bg=PANEL, fg=TXT, font=_font(10)
                 ).pack(anchor="w", padx=12)
        self.sym_var = tk.StringVar()
        tk.Entry(left, textvariable=self.sym_var, **ef, width=4
                 ).pack(anchor="w", padx=12, pady=(2, 6))

        tk.Label(left, text="Icon  (white row / black row)", bg=PANEL, fg=TXT, font=_font(10)
                 ).pack(anchor="w", padx=12)
        self.icon_picker = IconPickerCanvas(
            left, self.tk_icons,
            on_select=lambda sym: self._on_icon_select(sym))
        self.icon_picker.pack(padx=12, pady=(2, 6), anchor="w")

        tk.Frame(left, bg=BORD, height=1).pack(fill="x", padx=12, pady=6)

        # ── LEFT: save / close ────────────────────────────────────────────────
        bot = tk.Frame(left, bg=PANEL)
        bot.pack(fill="x", padx=12, pady=(0, 10), side="bottom")
        tk.Button(bot, text="Save Piece", command=self._save_piece,
                  bg=acc, fg="#0A0A0A", relief="flat", font=_font(11, bold=True),
                  padx=10, pady=6, cursor="hand2",
                  activebackground=acc, activeforeground="#0A0A0A"
                  ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(bot, text="Close", command=self._close,
                  **dict(bs, bg="#2E0E0E", fg="#E08080")
                  ).pack(side="left", expand=True, fill="x")

        # ── RIGHT: notebook ───────────────────────────────────────────────────
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # Tab 0 — Move Pattern
        tab_grid = tk.Frame(nb, bg=BG)
        nb.add(tab_grid, text="  Move Pattern  ")

        tk.Label(tab_grid, bg=BG, fg=DIM, font=_font(8),
                 text="Left-click: toggle   Right-click: cycle mode   "
                      "Middle-click: leap"
                 ).pack(anchor="w", padx=10, pady=(8, 2))

        self.grid_canvas = MoveGridCanvas(tab_grid)
        self.grid_canvas.pack(padx=10, pady=4, anchor="w")

        # Legend
        leg_row = tk.Frame(tab_grid, bg=BG)
        leg_row.pack(anchor="w", padx=10, pady=(2, 4))
        for col, label in [
            ("#41BE55", "Move+Capture"),
            ("#D24141", "Capture only"),
            ("#4173D2", "No-capture"),
            ("#C8A820", "L = leapable"),
        ]:
            dot = tk.Canvas(leg_row, width=12, height=12, bg=BG, highlightthickness=0)
            dot.create_oval(1, 1, 11, 11, fill=col, outline="")
            dot.pack(side="left", padx=(8, 2))
            tk.Label(leg_row, text=label, bg=BG, fg=DIM, font=_font(8)
                     ).pack(side="left", padx=(0, 8))

        self.sliding_var = tk.BooleanVar()
        tk.Checkbutton(tab_grid, text="Sliding piece  (auto-expands each target to steps 1-7)",
                       variable=self.sliding_var, command=self._on_sliding_toggle,
                       bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                       font=_font(10)).pack(anchor="w", padx=10, pady=4)

        # Tab 1 — Flags
        tab_flags = tk.Frame(nb, bg=BG)
        nb.add(tab_flags, text="  Flags  ")

        tk.Label(tab_flags, text="Behaviour Flags", bg=BG, fg=acc,
                 font=_font(12, bold=True)).pack(anchor="w", padx=14, pady=(12, 6))

        flag_defs = [
            ("is_royal",   "Is Royal  — losing this piece ends the game"),
            ("is_castler", "Is Castler  — can castle with the King"),
            ("cap_only",   "Can only capture (no quiet moves)"),
            ("nocap_only", "Can only move quietly (no captures)"),
        ]
        self.flag_vars = {}
        for key, desc in flag_defs:
            v = tk.BooleanVar()
            self.flag_vars[key] = v
            tk.Checkbutton(tab_flags, text=desc, variable=v,
                           bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                           font=_font(10)).pack(anchor="w", padx=14, pady=2)

        tk.Frame(tab_flags, bg=BORD, height=1).pack(fill="x", padx=14, pady=10)
        tk.Label(tab_flags, text="Lethality (AI piece-value multiplier)",
                 bg=BG, fg=acc, font=_font(10)).pack(anchor="w", padx=14, pady=(0, 2))
        self.lethality_var = tk.DoubleVar(value=1.0)
        tk.Scale(tab_flags, variable=self.lethality_var,
                 from_=0.1, to=4.0, resolution=0.1, orient="horizontal",
                 bg=BG, fg=TXT, troughcolor=SURF2, highlightthickness=0,
                 sliderrelief="flat", activebackground=acc,
                 font=_font(9)).pack(fill="x", padx=14, pady=(0, 8))

        tk.Frame(tab_flags, bg=BORD, height=1).pack(fill="x", padx=14, pady=6)
        tk.Label(tab_flags, text="Promotable to:", bg=BG, fg=acc,
                 font=_font(10)).pack(anchor="w", padx=14, pady=(0, 4))
        self._promo_frame = tk.Frame(tab_flags, bg=BG)
        self._promo_frame.pack(fill="x", padx=14)
        self._promo_vars = {}
        self._rebuild_promo_cbs()

        # Tab 2 — Multi-leg
        tab_ml = tk.Frame(nb, bg=PANEL)
        nb.add(tab_ml, text="  Multi-leg  ")
        self.ml_frame = MultilegFrame(tab_ml, accent=self.accent)
        self.ml_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.nb = nb

    # ── Piece list ─────────────────────────────────────────────────────────────
    def _refresh_piece_list(self, select_name=None):
        self.piece_list.delete(0, "end")
        for name in self.piece_types:
            self.piece_list.insert("end", f"  {name}")
        if select_name and select_name in self.piece_types:
            idx = list(self.piece_types.keys()).index(select_name)
            self.piece_list.selection_set(idx)
            self.piece_list.see(idx)
        self._rebuild_promo_cbs()

    def _on_list_sel(self, ev):
        sel = self.piece_list.curselection()
        if not sel: return
        name = self.piece_list.get(sel[0]).strip()
        if name in self.piece_types:
            self._load_piece(name)

    def _on_icon_select(self, sym):
        """
        Called when user clicks the icon picker.
        Updates symbol entry AND sets piece icon in the move grid centre cell.
        Uses a smaller 44px version of the icon (fits the grid cell comfortably).
        """
        self.sym_var.set(sym)
        # Load a small icon sized to fit the grid cell (CELL = 52 for the grid)
        grid_icon_size = 40
        icon = None
        root = None
        import os, json as _json
        _cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs.json")
        if os.path.isfile(_cfg_path):
            try:
                with open(_cfg_path) as _f: _cfg = _json.load(_f)
                active = _cfg.get("__active__", "")
                if active and active in _cfg and os.path.isdir(_cfg[active]):
                    root = _cfg[active]
            except Exception: pass
        if not root:
            here = os.path.dirname(os.path.abspath(__file__))
            for base in [here, os.getcwd()]:
                p = os.path.join(base, "assets", "chessmat")
                if os.path.isdir(p): root = p; break
        if root:
            fname = SYM_FILE.get(sym, sym.lower())
            # Try white version
            path = os.path.join(root, "white", f"{fname}.png")
            if not os.path.isfile(path):
                path = os.path.join(root, "black", f"{fname}.png")
            if os.path.isfile(path):
                try:
                    from PIL import Image as _PI, ImageTk as _PT
                    img = _PI.open(path).convert("RGBA").resize(
                        (grid_icon_size, grid_icon_size), _PI.LANCZOS)
                    icon = _PT.PhotoImage(img)
                    self._grid_icon_ref = icon   # keep reference alive
                except Exception as e:
                    print(f"[DEBUG editor] grid icon load error: {e}")
        self.grid_canvas.set_piece_icon(icon)
        print(f"[DEBUG editor] icon selected: {sym}, grid icon set")

    # ── Load / collect ─────────────────────────────────────────────────────────
    def _load_piece(self, name):
        pt = self.piece_types.get(name)
        if not pt: return
        self._editing = name
        self.name_var.set(pt.name)
        self.sym_var.set(pt.symbol)
        if pt.symbol in ALL_SYMS:
            self.icon_picker.selected = pt.symbol
            self.icon_picker._redraw()
            self._on_icon_select(pt.symbol)   # also update move grid icon
        self.lethality_var.set(pt.lethality)
        self.grid_canvas.load_piece(pt)

        sliding = any(len(r.legs) == 1 and r.legs[0].steps > 1
                      for r in pt.rules if not r.castling and not r.en_passant)
        self.sliding_var.set(sliding)
        self.grid_canvas.sliding = sliding

        self.flag_vars["is_royal"].set(pt.is_royal)
        self.flag_vars["is_castler"].set(pt.is_castler)
        self.flag_vars["cap_only"].set(False)
        self.flag_vars["nocap_only"].set(False)

        ml_rules = [r for r in pt.rules if len(r.legs) > 1]
        self.ml_frame.set_from_rules(ml_rules)
        self._rebuild_promo_cbs(pt.promotable_to)
        print(f"[DEBUG editor] loaded '{name}'")

    def _collect(self):
        """Assemble current UI state into a PieceType."""
        name   = self.name_var.get().strip() or "Custom"
        sym_raw = self.sym_var.get().strip()
        symbol  = sym_raw[0] if sym_raw else (self.icon_picker.selected or "?")
        rules   = self.grid_canvas.to_rules()
        if self.flag_vars["is_royal"].get():
            rules.append(MoveRule(castling=True))
        rules += self.ml_frame.get_move_rules()
        promo = [n for n, v in self._promo_vars.items() if v.get()]
        pt = PieceType(
            name=name, symbol=symbol, rules=rules,
            is_royal=self.flag_vars["is_royal"].get(),
            is_castler=self.flag_vars["is_castler"].get(),
            lethality=round(self.lethality_var.get(), 2),
            promotable_to=promo,
        )
        print(f"[DEBUG editor] collected '{name}' sym={symbol} rules={len(rules)} promo={promo}")
        return pt

    # ── Actions ────────────────────────────────────────────────────────────────
    def _new_piece(self):
        self._editing = None
        self.name_var.set("NewPiece")
        self.sym_var.set("?")
        self.lethality_var.set(1.0)
        self.grid_canvas.clear()
        for v in self.flag_vars.values(): v.set(False)
        self.ml_frame.rules = []
        self.ml_frame._cur_legs = []
        self.ml_frame._refresh_cur()
        self.ml_frame._refresh_rules()
        self.piece_list.selection_clear(0, "end")
        print("[DEBUG editor] new piece")

    def _delete_piece(self):
        if self._editing and self._editing in self.piece_types:
            if messagebox.askyesno("Delete", f"Delete '{self._editing}'?", parent=self):
                self.piece_types.pop(self._editing)
                self._editing = None
                self._refresh_piece_list()
                print("[DEBUG editor] piece deleted")

    def _save_piece(self):
        pt = self._collect()
        if self._editing and self._editing != pt.name:
            self.piece_types.pop(self._editing, None)
        self.piece_types[pt.name] = pt
        self._editing = pt.name
        self._refresh_piece_list(select_name=pt.name)
        if self.on_save_cb:
            self.on_save_cb(dict(self.piece_types))
        print(f"[DEBUG editor] saved '{pt.name}'")

    def _close(self):
        self.grab_release()
        self.destroy()

    def _on_sliding_toggle(self):
        self.grid_canvas.sliding = self.sliding_var.get()

    def _rebuild_promo_cbs(self, checked=None):
        for w in self._promo_frame.winfo_children(): w.destroy()
        self._promo_vars = {}
        names = list(self.piece_types.keys())
        if not names:
            tk.Label(self._promo_frame, text="(no pieces)",
                     bg=BG, fg=DIM, font=_font(9)).pack(anchor="w")
            return
        cols = 3
        for i, name in enumerate(names):
            v = tk.BooleanVar(value=(checked is not None and name in checked))
            self._promo_vars[name] = v
            tk.Checkbutton(self._promo_frame, text=name, variable=v,
                           bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                           font=_font(9)).grid(row=i//cols, column=i%cols,
                                               sticky="w", padx=4, pady=1)

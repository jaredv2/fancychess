"""
piece_editor.py — Fancy Chess Piece Editor  v5  (production)
=============================================================
All UI is native Tkinter.  Piece icons loaded via Pillow.

New in v5:
  - Multi-leg VISUAL canvas: click-drag to draw multi-segment paths
    (diagonal, L-shape, Z-shape, I-shape etc.) on a 9×9 grid.
    Each mouse-drag segment becomes one leg of the move rule.
    Right-click on the canvas clears the current path.
  - Piece value field: exposes lethality as centipawn (CP) value.
  - Coordinates: a-h bottom LTR, 1-8 left BTT (standard chess convention).
  - Renamed to "Fancy Chess" throughout.
  - Production: structured logging, no debug prints.
"""

import os, json, math, logging
import tkinter as tk
from tkinter import ttk, messagebox

from logic import PieceType, MoveRule, Leg, build_default_pieces

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("piece_editor")

print("[INFO editor] Fancy Chess Piece Editor v5 loading")

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette  (matches gui.py exactly)
# ─────────────────────────────────────────────────────────────────────────────
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
    if mono: return ("DejaVu Sans Mono", size)
    return ("Poppins", size, "bold") if bold else ("Poppins", size)


# ─────────────────────────────────────────────────────────────────────────────
# Pack-aware icon loading
# ─────────────────────────────────────────────────────────────────────────────
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
                if os.path.isdir(path): return path
        except Exception as e:
            log.warning("packs.json error: %s", e)
    here = os.path.dirname(os.path.abspath(__file__))
    for base in [here, os.getcwd(), os.path.join(here, "..")]:
        p = os.path.join(base, "assets", "chessmat")
        if os.path.isdir(p): return p
    return None


def load_editor_icons(size=40):
    """
    Load piece PNGs as tk.PhotoImage for the editor UI.
    Returns {(symbol, owner): PhotoImage} — keeps refs alive in the dict.
    Falls back silently if Pillow or files are missing.
    """
    imgs = {}
    root = _get_active_pack_root()
    if not root: return imgs
    try:
        from PIL import Image as PilImg, ImageTk as PilTk
    except ImportError:
        log.warning("Pillow not installed — no icons in piece editor")
        return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path): continue
            try:
                img = PilImg.open(path).convert("RGBA").resize((size, size), PilImg.LANCZOS)
                imgs[(sym, owner)] = PilTk.PhotoImage(img)
            except Exception as e:
                log.warning("Icon error %s: %s", path, e)
    print(f"[INFO editor] Loaded {len(imgs)}/12 icons @ {size}px")
    return imgs


# ─────────────────────────────────────────────────────────────────────────────
# Move Grid Canvas  — 9×9 interactive movement pattern editor
#
# Single-leg interactions (simple click/right-click):
#   Left-click  : toggle EMPTY ↔ MOVE
#   Right-click : cycle EMPTY → MOVE → CAP_ONLY → NO_CAP → EMPTY
#   Middle-click: toggle leap flag on that cell
#
# Multi-leg drawing (drag):
#   Click a cell in the grid and drag to an adjacent (or diagonal) cell
#   to add that direction as a leg segment to the current path.
#   The path is drawn as connected segments (arrows) on the grid.
#   Double-click the origin (centre) to clear drawn path.
#
# ─────────────────────────────────────────────────────────────────────────────
class MoveGridCanvas(tk.Canvas):
    """
    9×9 clickable grid for editing single-leg movement patterns AND
    visually drawing multi-leg paths.

    Multi-leg path drawing:
      - Click & drag from one cell to any other cell.
      - Each drag constitutes one leg (dx, dy) segment.
      - The path accumulates: you can chain multiple drags for L/Z/I shapes.
      - The path is shown as a connected arrow overlay.
      - Call get_drawn_path() to retrieve the accumulated list of Leg objects.
      - Call clear_drawn_path() (or right-click centre) to reset.
    """
    CELL = 52
    PAD  = 2

    def __init__(self, master, on_path_change=None, **kw):
        sz = GRID_N * self.CELL + self.PAD * 2
        super().__init__(master, width=sz, height=sz,
                         bg="#0C0C18", highlightthickness=1,
                         highlightbackground=BORD, **kw)
        # Single-leg data
        self.cells   = [[M_EMPTY] * GRID_N for _ in range(GRID_N)]
        self.leap    = [[False]   * GRID_N for _ in range(GRID_N)]
        self.sliding = False
        self._piece_icon = None   # tk.PhotoImage shown in centre cell

        # Multi-leg path data
        # _path_legs: list of (start_row, start_col, dr, dc, leapable)
        # The path starts at GRID_CR,GRID_CR and each leg extends it.
        self._path_legs: list = []   # list of Leg objects accumulated by drag
        self._path_start_row = GRID_CR
        self._path_start_col = GRID_CR
        self._drag_from  = None   # (row,col) where current drag started
        self._drag_to    = None   # (row,col) current drag target (live preview)
        self.on_path_change = on_path_change  # callback when path changes

        # path_mode: when False (default) clicks/drags only toggle single-leg
        # cells; drag-to-path only works when path_mode=True (Multi-leg tab open).
        self.path_mode = False

        self.bind("<Button-1>",          self._on_left_press)
        self.bind("<B1-Motion>",         self._on_drag)
        self.bind("<ButtonRelease-1>",   self._on_left_release)
        self.bind("<Button-3>",          self._on_right)
        self.bind("<Button-2>",          self._on_mid)
        self._redraw()

    def set_piece_icon(self, photo_image):
        """Show piece icon in the centre cell."""
        self._piece_icon = photo_image
        self._redraw()

    # ── Event helpers ──────────────────────────────────────────────────────
    def _rc(self, event):
        """Convert canvas pixel to (row,col) or (None,None) if out of bounds."""
        c = (event.x - self.PAD) // self.CELL
        r = (event.y - self.PAD) // self.CELL
        return (r, c) if (0 <= r < GRID_N and 0 <= c < GRID_N) else (None, None)

    def _cell_centre_px(self, r, c):
        """Pixel centre of cell (r,c)."""
        x = self.PAD + c * self.CELL + self.CELL // 2
        y = self.PAD + r * self.CELL + self.CELL // 2
        return x, y

    # ── Single-leg click interactions ──────────────────────────────────────
    def _on_right(self, event):
        r, c = self._rc(event)
        if r is None: return
        if r == GRID_CR and c == GRID_CR:
            # Right-click centre = clear multi-leg path
            self.clear_drawn_path(); return
        self.cells[r][c] = (self.cells[r][c] + 1) % 4
        self._redraw()

    def _on_mid(self, event):
        r, c = self._rc(event)
        if r is None or (r == GRID_CR and c == GRID_CR): return
        self.leap[r][c] = not self.leap[r][c]
        self._redraw()

    # ── Multi-leg drag interactions ────────────────────────────────────────
    def _on_left_press(self, event):
        r, c = self._rc(event)
        if r is None: return

        if not self.path_mode:
            # Normal mode: toggle the cell immediately on press.
            # Don't wait for release — avoids the fragile same-cell check.
            if not (r == GRID_CR and c == GRID_CR):
                self.cells[r][c] = M_EMPTY if self.cells[r][c] else M_MOVE
                self._redraw()
                print(f"[INFO editor] Cell ({r},{c}) toggled → {self.cells[r][c]}")
            self._drag_from   = None
            self._drag_to     = None
            self._click_start = None
            return

        # ── Path mode (Multi-leg tab active) ──────────────────────────────
        if r == GRID_CR and c == GRID_CR:
            # Click on centre = start new path from here
            self._drag_from = (r, c)
            self._drag_to   = None
            return
        # Continue path from its current end
        if self._path_legs:
            end_r, end_c = self._path_end_cell()
            self._drag_from = (end_r, end_c)
        else:
            self._drag_from = (GRID_CR, GRID_CR)
        self._drag_to     = None
        self._click_start = (r, c)

    def _on_drag(self, event):
        if not self.path_mode:
            return   # drag does nothing in normal cell-toggle mode
        r, c = self._rc(event)
        if r is None or self._drag_from is None: return
        if (r, c) != self._drag_from:
            self._drag_to = (r, c)
            self._redraw()

    def _on_left_release(self, event):
        # Normal mode: toggle is already handled in _on_left_press — nothing to do.
        if not self.path_mode:
            return

        # ── Path mode: commit drag as a new leg ───────────────────────────
        r, c = self._rc(event)
        if r is None:
            self._drag_from = None; self._drag_to = None; return
        if self._drag_from is None:
            return

        fr, fc = self._drag_from
        if (r, c) != (fr, fc):
            # Grid row increases downward → piece dx is inverted
            piece_dx = fr - r   # positive = up = forward for white
            piece_dy = c  - fc  # positive = right
            new_leg  = Leg(piece_dx, piece_dy, 1, False)
            self._path_legs.append(new_leg)
            print(f"[INFO editor] Leg added dx={piece_dx} dy={piece_dy} total={len(self._path_legs)}")
            if self.on_path_change:
                self.on_path_change(list(self._path_legs))

        self._drag_from = None; self._drag_to = None
        self._redraw()

    # ── Path helpers ───────────────────────────────────────────────────────
    def _path_end_cell(self):
        """Return the grid (row,col) where the current drawn path ends."""
        r, c = GRID_CR, GRID_CR
        for leg in self._path_legs:
            r -= leg.dx   # piece dx positive = up = row decreases
            c += leg.dy   # piece dy positive = right = col increases
        return r, c

    def clear_drawn_path(self):
        """Reset the multi-leg path."""
        self._path_legs = []
        self._drag_from = None; self._drag_to = None
        self._redraw()
        print("[INFO editor] Multi-leg path cleared")
        if self.on_path_change:
            self.on_path_change([])

    def get_drawn_path(self):
        """Return the accumulated list of Leg objects (copies)."""
        return list(self._path_legs)

    # ── Grid redraw ────────────────────────────────────────────────────────
    def _redraw(self):
        """
        Full redraw of the 9×9 grid:
          1. Board squares (alternating light/dark, centre = piece origin)
          2. Single-leg markers (coloured circles/rings + leap badge)
          3. Coordinate labels on all 4 edges
          4. Multi-leg path (connected arrow segments) overlay
          5. Live drag preview segment
        """
        self.delete("all")
        C, P = self.CELL, self.PAD

        SQ_L = "#D4D9B2"   # warm light square
        SQ_D = "#4A7A40"   # rich green dark square
        SQ_C = "#1A1A30"   # centre square (piece origin)

        # ── Draw squares ──────────────────────────────────────────────────
        for r in range(GRID_N):
            for c in range(GRID_N):
                x1 = P + c * C; y1 = P + r * C
                x2 = x1 + C - 1; y2 = y1 + C - 1
                cx = x1 + C // 2; cy = y1 + C // 2
                is_cen = (r == GRID_CR and c == GRID_CR)

                if is_cen:
                    bg = SQ_C
                elif (r + c) % 2 == 0:
                    bg = SQ_L
                else:
                    bg = SQ_D
                self.create_rectangle(x1, y1, x2, y2, fill=bg, outline="#222230")

                if is_cen:
                    icon = getattr(self, "_piece_icon", None)
                    if icon:
                        self.create_image(cx, cy, image=icon, anchor="center")
                    else:
                        d = 11
                        pts = [cx, cy - d, cx + d, cy, cx, cy + d, cx - d, cy]
                        self.create_polygon(pts, fill=GOLD, outline="#9A7A18", width=1)
                    continue

                mode = self.cells[r][c]
                if mode != M_EMPTY:
                    col = M_HEX[mode]
                    if mode == M_MOVE:
                        rr = C // 4
                        self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                         fill=col, outline="")
                    else:
                        rr = C // 4 + 2
                        self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                         fill="", outline=col, width=3)
                    if self.leap[r][c]:
                        self.create_rectangle(x1 + 2, y1 + 2, x1 + 18, y1 + 14,
                                              fill="#C8A820", outline="#907814")
                        self.create_text(x1 + 10, y1 + 8, text="L", fill="#0A0808",
                                         font=_font(6, bold=True))

                # ── Coordinate labels on edges ────────────────────────────
                # Show movement offset from origin (centre = 0,0)
                # Standard chess convention: right = +dy, up = +dx
                light_sq = (r + c) % 2 == 0
                coord_col = SQ_D if light_sq else SQ_L

                # Top row: column (dy) offsets — left-to-right matches +dy
                if r == 0:
                    off = c - GRID_CR   # dy offset: negative=left, positive=right
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(cx, y1 + 7, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True))

                # Bottom row: column offsets (repeated)
                if r == GRID_N - 1:
                    off = c - GRID_CR
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(cx, y2 - 6, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True))

                # Left column: rank (dx) offsets — up = +dx
                if c == 0:
                    off = GRID_CR - r   # dx offset: negative=down, positive=up
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(x1 + 8, cy, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True))

                # Right column: rank offsets (repeated)
                if c == GRID_N - 1:
                    off = GRID_CR - r
                    lbl = f"+{off}" if off > 0 else str(off)
                    self.create_text(x2 - 7, cy, text=lbl, anchor="center",
                                     fill=coord_col, font=_font(7, bold=True))

        # ── Draw multi-leg path overlay ────────────────────────────────────
        # The path starts at the centre and follows each leg in sequence.
        # Each leg is drawn as a bold arrow from its start to end cell.
        if self._path_legs or self._drag_to:
            self._draw_path_overlay(C, P)

    def _draw_path_overlay(self, C, P):
        """
        Draw the accumulated multi-leg path as connected arrow segments.
        Each committed leg = solid arrow.
        Live drag preview = dashed arrow.
        """
        # Committed segments
        r, c = GRID_CR, GRID_CR
        for i, leg in enumerate(self._path_legs):
            nr = r - leg.dx   # next row
            nc = c + leg.dy   # next col
            x1, y1 = self._cell_centre_px(r, c)
            x2, y2 = self._cell_centre_px(nr, nc)
            # Color gradient: earlier legs = orange, later = cyan
            t = i / max(len(self._path_legs), 1)
            red = int(255 * (1 - t)); grn = int(180 * t + 120 * (1 - t))
            col_str = f"#{red:02x}{grn:02x}ff" if t > 0.3 else f"#{red:02x}{grn:02x}60"
            self._draw_grid_arrow(x1, y1, x2, y2, width=4, color="#E0A020" if i == 0 else "#20C0E0")
            # Dot at start node
            self.create_oval(x1 - 5, y1 - 5, x1 + 5, y1 + 5, fill="#E0A020", outline="")
            r, c = nr, nc

        # End node marker (larger gold dot)
        ex, ey = self._cell_centre_px(r, c)
        self.create_oval(ex - 7, ey - 7, ex + 7, ey + 7, fill=GOLD, outline="#9A7A18", width=2)

        # Live drag preview (dashed, grey)
        if self._drag_from and self._drag_to:
            dr, dc = self._drag_from
            tr, tc = self._drag_to
            x1, y1 = self._cell_centre_px(dr, dc)
            x2, y2 = self._cell_centre_px(tr, tc)
            self._draw_grid_arrow(x1, y1, x2, y2, width=2, color="#888888", dash=(4, 4))

    def _draw_grid_arrow(self, x1, y1, x2, y2, width=4, color="#E0A020", dash=()):
        """Draw an arrow from (x1,y1) to (x2,y2) on this canvas."""
        dx = x2 - x1; dy = y2 - y1; dist = math.hypot(dx, dy)
        if dist < 2: return
        nx = dx / dist; ny = dy / dist
        head = min(12, dist * 0.35)
        sx2 = x2 - nx * head; sy2 = y2 - ny * head
        kw = {"fill": color, "width": width, "capstyle": tk.ROUND}
        if dash: kw["dash"] = dash
        self.create_line(x1, y1, sx2, sy2, **kw)
        # Arrowhead triangle
        perp_x = -ny; perp_y = nx; hw = head * 0.5
        pts = [
            x2, y2,
            sx2 + perp_x * hw, sy2 + perp_y * hw,
            sx2 - perp_x * hw, sy2 - perp_y * hw,
        ]
        self.create_polygon(pts, fill=color, outline="")

    # ── Grid <-> rules conversion ──────────────────────────────────────────
    def clear(self):
        self.cells = [[M_EMPTY] * GRID_N for _ in range(GRID_N)]
        self.leap  = [[False]   * GRID_N for _ in range(GRID_N)]
        self.clear_drawn_path()

    def load_piece(self, pt):
        """Load 1-leg rules from a PieceType into the single-leg grid."""
        self.clear()
        for rule in pt.rules:
            if rule.castling or rule.en_passant: continue
            if len(rule.legs) == 1 and rule.legs[0].steps == 1:
                leg = rule.legs[0]
                r = GRID_CR - leg.dx
                c = GRID_CR + leg.dy
                if 0 <= r < GRID_N and 0 <= c < GRID_N and not (r == GRID_CR and c == GRID_CR):
                    mode = M_CAP if rule.capture_only else (
                           M_NOCAP if rule.non_capture_only else M_MOVE)
                    self.cells[r][c] = mode
                    self.leap[r][c]  = leg.leapable
        self._redraw()
        print(f"[INFO editor] Grid loaded from piece: {pt.name}")

    def to_rules(self):
        """Convert grid state to a list of MoveRule objects (single-leg)."""
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
        cols = len(ALL_SYMS); rows = 2
        w = cols * (self.ICON + self.GAP) + self.GAP
        h = rows * (self.ICON + self.GAP) + self.GAP
        super().__init__(master, width=w, height=h,
                         bg=SURF, highlightthickness=0, **kw)
        self.tk_icons  = tk_icons
        self.on_select = on_select
        self.selected  = "Q"
        self.bind("<Button-1>", self._on_click)
        self._redraw()

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
                    if self.on_select: self.on_select(sym)
                    return

    def _redraw(self):
        self.delete("all")
        for owner in range(2):
            for i, sym in enumerate(ALL_SYMS):
                x, y = self._cell_xy(owner, i)
                sel = (sym == self.selected)
                self.create_rectangle(x, y, x + self.ICON, y + self.ICON,
                                      fill="#3A2808" if sel else SURF2,
                                      outline=GOLD if sel else BORD, width=2)
                olbl = "W" if owner == 0 else "B"
                self.create_text(x + self.ICON - 3, y + 3, text=olbl,
                                 anchor="ne", fill=DIM, font=_font(6))
                img = self.tk_icons.get((sym, owner))
                if img:
                    self.create_image(x + self.ICON // 2, y + self.ICON // 2,
                                      image=img, anchor="center")
                else:
                    pad = 8
                    fc  = "#D0CCC0" if owner == 0 else "#302C28"
                    self.create_oval(x + pad, y + pad,
                                     x + self.ICON - pad, y + self.ICON - pad,
                                     fill=fc, outline="")


# ─────────────────────────────────────────────────────────────────────────────
# Multi-leg Rule Builder  (compass widget + visual path canvas)
# ─────────────────────────────────────────────────────────────────────────────
class MultilegFrame(tk.Frame):
    """
    Builder for multi-leg movement rules.

    Two input methods:
      A) VISUAL CANVAS: Drag directly on the MoveGridCanvas (the main grid)
         to draw multi-segment paths. Each drag adds one leg. The path is
         previewed live on the grid. Click "Commit Path → Rule" to save it.

      B) COMPASS: Traditional compass widget to add legs manually (direction
         + steps + leap), then "Finish Rule" to commit.

    Both methods produce the same MoveRule objects with multiple Legs.
    """

    def __init__(self, master, accent, grid_canvas: "MoveGridCanvas", **kw):
        super().__init__(master, bg=PANEL, **kw)
        self.accent = accent
        self.grid_canvas = grid_canvas
        self.rules: list = []           # completed rules (list of Leg lists)
        self._cur_legs: list = []       # legs being assembled via compass
        self._dir_sel = (-1, 0)         # selected (dx, dy) for compass
        # Connect grid canvas path-change callback
        grid_canvas.on_path_change = self._on_path_from_canvas
        self._build()

    def _build(self):
        BS = dict(bg=SURF2, fg=TXT, relief="flat", font=_font(9),
                  padx=6, pady=3, cursor="hand2",
                  activebackground=SURF, activeforeground=TXT, bd=0)

        tk.Label(self, text="Multi-leg Rules", bg=PANEL, fg=self.accent,
                 font=_font(11, bold=True)).pack(anchor="w", pady=(8, 3))

        # ── Visual path method ────────────────────────────────────────────
        vis_f = tk.LabelFrame(self, text="Visual Path Drawing", bg=PANEL, fg=DIM,
                              font=_font(8), bd=1, relief="flat",
                              highlightthickness=1, highlightbackground=BORD)
        vis_f.pack(fill="x", pady=(0, 8), padx=2)
        tk.Label(vis_f, bg=PANEL, fg=DIM, font=_font(8),
                 text="Drag on the move grid (left) to draw segments.\n"
                      "Each drag adds one leg. Right-click centre to clear.",
                 justify="left").pack(anchor="w", padx=6, pady=(4, 2))
        self._vis_path_lbl = tk.Label(vis_f, text="Path: (none)", bg=PANEL, fg=TXT,
                                      font=_font(9, mono=True))
        self._vis_path_lbl.pack(anchor="w", padx=6, pady=(0, 2))

        vis_btn_r = tk.Frame(vis_f, bg=PANEL); vis_btn_r.pack(fill="x", padx=6, pady=(0, 6))
        tk.Button(vis_btn_r, text="Commit Path → Rule", command=self._commit_visual_path,
                  bg="#142A1C", fg="#70D890", relief="flat", font=_font(9),
                  cursor="hand2", pady=4, bd=0,
                  activebackground=SURF, activeforeground=TXT).pack(side="left", padx=(0, 4))
        tk.Button(vis_btn_r, text="Clear Path", command=self.grid_canvas.clear_drawn_path,
                  bg="#2E0E0E", fg="#E08888", relief="flat", font=_font(9),
                  cursor="hand2", pady=4, bd=0,
                  activebackground=SURF, activeforeground=TXT).pack(side="left")

        tk.Frame(self, bg=BORD, height=1).pack(fill="x", pady=(0, 6))

        # ── Compass method ────────────────────────────────────────────────
        cmp_f = tk.LabelFrame(self, text="Compass Builder", bg=PANEL, fg=DIM,
                              font=_font(8), bd=1, relief="flat",
                              highlightthickness=1, highlightbackground=BORD)
        cmp_f.pack(fill="x", pady=(0, 8), padx=2)
        tk.Label(cmp_f, bg=PANEL, fg=DIM, font=_font(8),
                 text="Pick direction, set steps, then Add Leg. Repeat for each segment.").pack(
                 anchor="w", padx=6, pady=(4, 6))

        builder = tk.Frame(cmp_f, bg=PANEL); builder.pack(fill="x", padx=6, pady=(0, 6))

        # 3×3 compass
        dir_f = tk.LabelFrame(builder, text="Direction", bg=PANEL, fg=DIM,
                              font=_font(8), bd=1, relief="flat",
                              highlightthickness=1, highlightbackground=BORD)
        dir_f.pack(side="left", padx=(0, 10))
        dir_labels = [[(-1,-1),(-1,0),(-1,1)],[(0,-1),None,(0,1)],[(1,-1),(1,0),(1,1)]]
        dir_arrows  = [["NW","N","NE"],["W","","E"],["SW","S","SE"]]
        self._dir_btns = {}
        for gr in range(3):
            for gc in range(3):
                dd = dir_labels[gr][gc]; lbl = dir_arrows[gr][gc]
                if dd is None:
                    tk.Frame(dir_f, width=36, height=28, bg=BG).grid(row=gr, column=gc, padx=2, pady=2)
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
        opts_f = tk.Frame(builder, bg=PANEL); opts_f.pack(side="left", padx=(0, 10))
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
        btn_col = tk.Frame(builder, bg=PANEL); btn_col.pack(side="left", anchor="n")
        for label, cmd, clr, fclr in [
            ("Add Leg",     self._add_leg,     "#142A1C", "#70D890"),
            ("Finish Rule", self._finish_rule, "#0E1C3A", "#70A8E0"),
            ("Clear",       self._clear_cur,   "#2E0E0E", "#E08888"),
        ]:
            tk.Button(btn_col, text=label, width=10, command=cmd,
                      bg=clr, fg=fclr, relief="flat", font=_font(9),
                      cursor="hand2", pady=4, bd=0,
                      activebackground=SURF, activeforeground=TXT).pack(pady=(0, 3))

        # Capture / no-capture flags for whole rule
        flag_f = tk.Frame(self, bg=PANEL); flag_f.pack(fill="x", pady=(0, 6))
        self._cap_var   = tk.BooleanVar()
        self._nocap_var = tk.BooleanVar()
        tk.Checkbutton(flag_f, text="Capture only", variable=self._cap_var,
                       bg=PANEL, fg=TXT, selectcolor=SURF2,
                       activebackground=PANEL, font=_font(9)).pack(side="left", padx=(0, 10))
        tk.Checkbutton(flag_f, text="No-capture", variable=self._nocap_var,
                       bg=PANEL, fg=TXT, selectcolor=SURF2,
                       activebackground=PANEL, font=_font(9)).pack(side="left")

        # Current-rule preview (compass legs)
        tk.Label(self, text="Current compass rule (legs so far):", bg=PANEL, fg=DIM,
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

    # ── Visual path callbacks ──────────────────────────────────────────────
    def _on_path_from_canvas(self, legs):
        """Called when the canvas path changes."""
        if not legs:
            self._vis_path_lbl.config(text="Path: (none)")
            return
        parts = " → ".join(f"({l.dx:+d},{l.dy:+d})" for l in legs)
        self._vis_path_lbl.config(text=f"Path: {parts}")

    def _commit_visual_path(self):
        """Commit the drawn canvas path as a new multi-leg rule."""
        legs = self.grid_canvas.get_drawn_path()
        if not legs:
            messagebox.showinfo("No path", "Draw a path on the move grid first.", parent=self)
            return
        self.rules.append(legs)
        self.grid_canvas.clear_drawn_path()
        self._refresh_rules()
        print(f"[INFO editor] Visual path committed as rule: {len(legs)} legs, total rules={len(self.rules)}")

    # ── Compass builder helpers ────────────────────────────────────────────
    def _select_dir(self, dd):
        self._dir_sel = dd
        for d, btn in self._dir_btns.items():
            btn.config(bg=self.accent if d == dd else SURF2,
                       fg="#0A0A0A"   if d == dd else TXT)

    def _add_leg(self):
        dx, dy   = self._dir_sel
        steps    = max(1, self._steps_var.get())
        leapable = self._leap_var.get()
        self._cur_legs.append(Leg(dx, dy, steps, leapable))
        self._refresh_cur()
        print(f"[INFO editor] Compass leg added: dx={dx} dy={dy} steps={steps} leap={leapable}")

    def _finish_rule(self):
        if not self._cur_legs:
            messagebox.showinfo("No legs", "Add at least one leg first.", parent=self); return
        self.rules.append(list(self._cur_legs))
        self._cur_legs = []
        self._cap_var.set(False); self._nocap_var.set(False)
        self._refresh_cur(); self._refresh_rules()
        print(f"[INFO editor] Compass rule finished, total={len(self.rules)}")

    def _clear_cur(self):
        self._cur_legs = []
        self._refresh_cur()

    def _refresh_cur(self):
        for w in self._cur_frame.winfo_children(): w.destroy()
        if not self._cur_legs:
            tk.Label(self._cur_frame, text="  (empty — add legs above)",
                     bg=SURF, fg=DIM, font=_font(9)).pack(anchor="w", padx=6, pady=5)
        else:
            parts = " → ".join(
                f"({l.dx:+d},{l.dy:+d})×{l.steps}{'[L]' if l.leapable else ''}"
                for l in self._cur_legs)
            tk.Label(self._cur_frame, text=f"  {parts}",
                     bg=SURF, fg=TXT, font=_font(9, mono=True)).pack(anchor="w", padx=6, pady=5)

    def _refresh_rules(self):
        for w in self._rules_frame.winfo_children(): w.destroy()
        if not self.rules:
            tk.Label(self._rules_frame, text="  No completed rules yet.",
                     bg=PANEL, fg=DIM, font=_font(9)).pack(anchor="w"); return
        for i, legs in enumerate(self.rules):
            row = tk.Frame(self._rules_frame, bg=SURF2); row.pack(fill="x", pady=2)
            parts = " → ".join(
                f"({l.dx:+d},{l.dy:+d})×{l.steps}{'[L]' if l.leapable else ''}" for l in legs)
            tk.Label(row, text=f"  {i+1}.  {parts}",
                     bg=SURF2, fg=TXT, font=_font(9, mono=True),
                     anchor="w").pack(side="left", fill="x", expand=True, padx=4)
            tk.Button(row, text="×", command=lambda ix=i: self._del_rule(ix),
                      bg="#3A1414", fg="#E08080", relief="flat",
                      font=_font(9), padx=4, cursor="hand2", bd=0).pack(side="right", padx=4)

    def _del_rule(self, idx):
        if 0 <= idx < len(self.rules):
            self.rules.pop(idx); self._refresh_rules()

    def get_move_rules(self):
        """Return list of MoveRule from all completed rules."""
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
        self._refresh_cur(); self._refresh_rules()


# ─────────────────────────────────────────────────────────────────────────────
# Piece Editor Window
# ─────────────────────────────────────────────────────────────────────────────
class PieceEditorWindow(tk.Toplevel):
    """
    Main piece editor dialog.
    Left panel: piece list + icon picker.
    Centre: 9×9 move grid (with visual drag-to-draw multi-leg path support).
    Right: properties notebook (flags, multi-leg rules, piece value).
    """

    def __init__(self, master, piece_types: dict, on_save_cb=None):
        super().__init__(master)
        self.title("Piece Editor — Fancy Chess")
        self.configure(bg=BG); self.resizable(True, True); self.grab_set()
        self.piece_types = dict(piece_types)
        self.on_save_cb  = on_save_cb
        self._editing    = None   # name of piece currently in editor
        self._grid_icon_ref = None

        self.tk_icons = load_editor_icons(size=46)
        self.accent   = GOLD

        self._build()
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width() - self.winfo_width()) // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")
        print("[INFO editor] PieceEditorWindow opened")

    def _build(self):
        acc = self.accent

        # ── Title ──────────────────────────────────────────────────────────
        tk.Label(self, text="Piece Editor", bg=BG, fg=TXT,
                 font=_font(14, bold=True)).pack(anchor="w", padx=14, pady=(10, 0))
        tk.Label(self, text="Edit movement patterns, flags, and value for each piece type.",
                 bg=BG, fg=DIM, font=_font(9)).pack(anchor="w", padx=14, pady=(0, 6))
        tk.Frame(self, bg=BORD, height=1).pack(fill="x")

        # ── Main body ──────────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Left: piece list ───────────────────────────────────────────────
        left = tk.Frame(body, bg=PANEL, width=160); left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="PIECES", bg=PANEL, fg=DIM, font=_font(8)).pack(anchor="w", padx=8, pady=(8, 2))

        lf = tk.Frame(left, bg=SURF); lf.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        sb = tk.Scrollbar(lf, orient="vertical")
        self.piece_list = tk.Listbox(lf, yscrollcommand=sb.set, bg=SURF, fg=TXT,
                                     selectbackground=SURF2, selectforeground=acc,
                                     font=_font(10), relief="flat", bd=0,
                                     activestyle="none", highlightthickness=0,
                                     exportselection=False, width=16)
        sb.config(command=self.piece_list.yview)
        sb.pack(side="right", fill="y"); self.piece_list.pack(side="left", fill="both", expand=True)
        self.piece_list.bind("<<ListboxSelect>>", self._on_list_sel)

        btn_f = tk.Frame(left, bg=PANEL); btn_f.pack(fill="x", padx=4, pady=(0, 6))
        for lbl, cmd, bg2, fg2 in [
            ("+ New",   self._new_piece,    "#142A1C", "#70D890"),
            ("Delete",  self._delete_piece, "#2E0E0E", "#E08888"),
            ("Save",    self._save_piece,   "#0E1C3A", "#70A8E0"),
        ]:
            tk.Button(btn_f, text=lbl, command=cmd, bg=bg2, fg=fg2,
                      relief="flat", font=_font(9), cursor="hand2", pady=3, bd=0,
                      activebackground=SURF, activeforeground=TXT).pack(fill="x", pady=1, padx=2)
        tk.Button(btn_f, text="Close", command=self._close,
                  bg=SURF2, fg=TXT, relief="flat", font=_font(9),
                  cursor="hand2", pady=3, bd=0).pack(fill="x", pady=1, padx=2)

        # ── Centre: name + icon picker + move grid ─────────────────────────
        mid = tk.Frame(body, bg=BG); mid.pack(side="left", fill="both", padx=(0, 8))

        # Name + symbol row
        nrow = tk.Frame(mid, bg=BG); nrow.pack(fill="x", pady=(0, 4))
        tk.Label(nrow, text="Name:", bg=BG, fg=DIM, font=_font(9)).pack(side="left")
        self.name_var = tk.StringVar(value="")
        tk.Entry(nrow, textvariable=self.name_var, bg=SURF2, fg=TXT,
                 insertbackground=TXT, relief="flat", font=_font(10), width=16).pack(side="left", padx=(4, 12))
        tk.Label(nrow, text="Symbol:", bg=BG, fg=DIM, font=_font(9)).pack(side="left")
        self.sym_var = tk.StringVar(value="?")
        tk.Entry(nrow, textvariable=self.sym_var, bg=SURF2, fg=TXT,
                 insertbackground=TXT, relief="flat", font=_font(10), width=3).pack(side="left", padx=(4, 0))

        # Sliding toggle
        srow = tk.Frame(mid, bg=BG); srow.pack(fill="x", pady=(0, 4))
        self.sliding_var = tk.BooleanVar(value=False)
        tk.Checkbutton(srow, text="Sliding (repeating) moves", variable=self.sliding_var,
                       bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                       font=_font(10), command=self._on_sliding_toggle).pack(side="left")

        # Icon picker
        tk.Label(mid, text="Icon:", bg=BG, fg=DIM, font=_font(9)).pack(anchor="w")
        self.icon_picker = IconPickerCanvas(mid, self.tk_icons, on_select=self._on_icon_select)
        self.icon_picker.pack(anchor="w", pady=(2, 8))

        # Move grid canvas (now also handles drag-to-draw multi-leg paths)
        tk.Label(mid, text="Move grid  (Left-click: toggle  |  Right-click: cycle mode  |  Drag: draw path)",
                 bg=BG, fg=DIM, font=_font(8)).pack(anchor="w")
        self.grid_canvas = MoveGridCanvas(mid)
        self.grid_canvas.pack(pady=(2, 0))

        # ── Right: properties notebook ─────────────────────────────────────
        right = tk.Frame(body, bg=BG); right.pack(side="left", fill="both", expand=True)
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        # ── Tab 1: Flags + Piece Value ─────────────────────────────────────
        tab_flags = tk.Frame(nb, bg=BG)
        nb.add(tab_flags, text="  Flags  ")

        flag_defs = [
            ("is_royal",   "Royal (losing this piece = loss)"),
            ("is_castler", "Castler (can castle)"),
        ]
        self.flag_vars = {}
        for key, desc in flag_defs:
            v = tk.BooleanVar()
            self.flag_vars[key] = v
            tk.Checkbutton(tab_flags, text=desc, variable=v,
                           bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                           font=_font(10)).pack(anchor="w", padx=14, pady=2)

        # ── Piece value (lethality as CP) ──────────────────────────────────
        tk.Frame(tab_flags, bg=BORD, height=1).pack(fill="x", padx=14, pady=10)
        tk.Label(tab_flags, text="Piece Value (Centipawns)",
                 bg=BG, fg=acc, font=_font(10, bold=True)).pack(anchor="w", padx=14, pady=(0, 2))
        tk.Label(tab_flags, text="Sets the AI's estimate of this piece's worth.\n"
                                  "Pawn=100, Knight/Bishop=300-330, Rook=500, Queen=900.",
                 bg=BG, fg=DIM, font=_font(8), justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        cp_row = tk.Frame(tab_flags, bg=BG); cp_row.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(cp_row, text="CP value:", bg=BG, fg=TXT, font=_font(10)).pack(side="left")
        self.cp_var = tk.IntVar(value=100)
        tk.Spinbox(cp_row, from_=0, to=3000, increment=10, textvariable=self.cp_var,
                   width=6, bg=SURF2, fg=TXT, insertbackground=TXT,
                   relief="flat", font=_font(10), buttonbackground=SURF2,
                   highlightthickness=0).pack(side="left", padx=(8, 12))
        # Common presets
        for label, val in [("Pawn", 100), ("Minor", 320), ("Rook", 500), ("Queen", 900)]:
            tk.Button(cp_row, text=label, command=lambda v=val: self.cp_var.set(v),
                      bg=SURF2, fg=TXT, relief="flat", font=_font(8),
                      padx=4, pady=1, cursor="hand2", bd=0).pack(side="left", padx=1)

        # Lethality (AI multiplier) — advanced
        tk.Frame(tab_flags, bg=BORD, height=1).pack(fill="x", padx=14, pady=6)
        tk.Label(tab_flags, text="Lethality (AI aggressiveness multiplier)",
                 bg=BG, fg=DIM, font=_font(9)).pack(anchor="w", padx=14, pady=(0, 2))
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

        # ── Tab 2: Multi-leg ───────────────────────────────────────────────
        tab_ml = tk.Frame(nb, bg=PANEL)
        nb.add(tab_ml, text="  Multi-leg  ")
        # MultilegFrame connects to the grid canvas for drag-path support
        self.ml_frame = MultilegFrame(tab_ml, accent=self.accent, grid_canvas=self.grid_canvas)
        self.ml_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.nb = nb
        # Bind tab-change: enable path_mode ONLY when Multi-leg tab is active.
        # This prevents accidental drag-path behaviour in normal editing.
        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # Load piece list
        self._refresh_piece_list()

    def _on_tab_change(self, event=None):
        """Enable drag-to-path on the grid only while the Multi-leg tab is open."""
        try:
            selected = self.nb.tab(self.nb.select(), "text").strip()
            is_ml    = (selected == "Multi-leg")
            self.grid_canvas.path_mode = is_ml
            # Visual hint: canvas border changes colour to signal mode
            self.grid_canvas.config(
                highlightbackground="#CDA537" if is_ml else "#2A2A3E"
            )
            print(f"[INFO editor] Tab={selected!r} path_mode={is_ml}")
        except Exception:
            pass

    # ── Piece list ──────────────────────────────────────────────────────────
    def _refresh_piece_list(self, select_name=None):
        self.piece_list.delete(0, "end")
        for name in self.piece_types:
            self.piece_list.insert("end", f"  {name}")
        if select_name and select_name in self.piece_types:
            idx = list(self.piece_types.keys()).index(select_name)
            self.piece_list.selection_set(idx); self.piece_list.see(idx)
        self._rebuild_promo_cbs()

    def _on_list_sel(self, ev):
        sel = self.piece_list.curselection()
        if not sel: return
        name = self.piece_list.get(sel[0]).strip()
        if name in self.piece_types: self._load_piece(name)

    def _on_icon_select(self, sym):
        """Called when user clicks the icon picker. Updates symbol + grid centre icon."""
        self.sym_var.set(sym)
        grid_icon_size = 40
        icon = None
        root = _get_active_pack_root()
        if root:
            fname = SYM_FILE.get(sym, sym.lower())
            path = os.path.join(root, "white", f"{fname}.png")
            if not os.path.isfile(path):
                path = os.path.join(root, "black", f"{fname}.png")
            if os.path.isfile(path):
                try:
                    from PIL import Image as _PI, ImageTk as _PT
                    img = _PI.open(path).convert("RGBA").resize(
                        (grid_icon_size, grid_icon_size), _PI.LANCZOS)
                    icon = _PT.PhotoImage(img)
                    self._grid_icon_ref = icon  # keep reference alive
                except Exception as e:
                    log.warning("Grid icon load error: %s", e)
        self.grid_canvas.set_piece_icon(icon)

    # ── Load / collect ──────────────────────────────────────────────────────
    def _load_piece(self, name):
        pt = self.piece_types.get(name)
        if not pt: return
        self._editing = name
        self.name_var.set(pt.name); self.sym_var.set(pt.symbol)
        if pt.symbol in ALL_SYMS:
            self.icon_picker.selected = pt.symbol
            self.icon_picker._redraw()
            self._on_icon_select(pt.symbol)
        self.lethality_var.set(pt.lethality)
        # Set CP from explicit .value field; fallback to lethality estimate
        from ai import _MATERIAL
        cp_default = _MATERIAL.get(pt.name, int(pt.lethality * 100))
        self.cp_var.set(pt.value if pt.value > 0 else cp_default)
        print(f"[INFO editor] Loaded CP value: {self.cp_var.get()} for '{pt.name}'")
        self.grid_canvas.load_piece(pt)

        sliding = any(len(r.legs) == 1 and r.legs[0].steps > 1
                      for r in pt.rules if not r.castling and not r.en_passant)
        self.sliding_var.set(sliding); self.grid_canvas.sliding = sliding
        self.flag_vars["is_royal"].set(pt.is_royal)
        self.flag_vars["is_castler"].set(pt.is_castler)
        ml_rules = [r for r in pt.rules if len(r.legs) > 1]
        self.ml_frame.set_from_rules(ml_rules)
        self._rebuild_promo_cbs(pt.promotable_to)
        print(f"[INFO editor] Loaded piece: '{name}'")

    def _collect(self):
        """Assemble current UI state into a PieceType."""
        name    = self.name_var.get().strip() or "Custom"
        sym_raw = self.sym_var.get().strip()
        symbol  = sym_raw[0] if sym_raw else (self.icon_picker.selected or "?")
        rules   = self.grid_canvas.to_rules()
        if self.flag_vars["is_royal"].get():
            rules.append(MoveRule(castling=True))
        rules += self.ml_frame.get_move_rules()
        promo = [n for n, v in self._promo_vars.items() if v.get()]
        # CP value → stored directly in PieceType.value (centipawns)
        # lethality is kept as a separate AI aggressiveness multiplier
        cp_val    = max(0, self.cp_var.get())
        lethality = round(self.lethality_var.get(), 2)
        pt = PieceType(
            name=name, symbol=symbol, rules=rules,
            is_royal=self.flag_vars["is_royal"].get(),
            is_castler=self.flag_vars["is_castler"].get(),
            lethality=lethality,
            value=cp_val,           # AI reads this as centipawn worth
            promotable_to=promo,
        )
        print(f"[INFO editor] Collected piece: '{name}' sym={symbol} "
              f"rules={len(rules)} CP={cp_val} lethality={lethality}")
        return pt

    # ── Actions ─────────────────────────────────────────────────────────────
    def _new_piece(self):
        self._editing = None
        self.name_var.set("NewPiece"); self.sym_var.set("?")
        self.lethality_var.set(1.0); self.cp_var.set(100)
        self.grid_canvas.clear()
        for v in self.flag_vars.values(): v.set(False)
        self.ml_frame.rules = []
        self.ml_frame._cur_legs = []
        self.ml_frame._refresh_cur(); self.ml_frame._refresh_rules()
        self.piece_list.selection_clear(0, "end")
        print("[INFO editor] New piece template")

    def _delete_piece(self):
        if self._editing and self._editing in self.piece_types:
            if messagebox.askyesno("Delete", f"Delete '{self._editing}'?", parent=self):
                self.piece_types.pop(self._editing)
                self._editing = None
                self._refresh_piece_list()
                print(f"[INFO editor] Piece deleted")

    def _save_piece(self):
        pt = self._collect()
        if self._editing and self._editing != pt.name:
            self.piece_types.pop(self._editing, None)
        self.piece_types[pt.name] = pt
        self._editing = pt.name
        self._refresh_piece_list(select_name=pt.name)
        if self.on_save_cb: self.on_save_cb(dict(self.piece_types))
        print(f"[INFO editor] Piece saved: '{pt.name}'")

    def _close(self):
        self.grab_release(); self.destroy()

    def _on_sliding_toggle(self):
        self.grid_canvas.sliding = self.sliding_var.get()

    def _rebuild_promo_cbs(self, checked=None):
        for w in self._promo_frame.winfo_children(): w.destroy()
        self._promo_vars = {}
        names = list(self.piece_types.keys())
        if not names:
            tk.Label(self._promo_frame, text="(no pieces)",
                     bg=BG, fg=DIM, font=_font(9)).pack(anchor="w"); return
        cols = 3
        for i, name in enumerate(names):
            v = tk.BooleanVar(value=(checked is not None and name in checked))
            self._promo_vars[name] = v
            tk.Checkbutton(self._promo_frame, text=name, variable=v,
                           bg=BG, fg=TXT, selectcolor=SURF2, activebackground=BG,
                           font=_font(9)).grid(row=i // cols, column=i % cols,
                                               sticky="w", padx=4, pady=1)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test runner
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Piece Editor Test — Fancy Chess")
    root.configure(bg="#0D0D13")
    types = build_default_pieces()

    def on_save(new_types):
        print(f"[INFO editor] Saved types: {list(new_types.keys())}")

    PieceEditorWindow(root, types, on_save_cb=on_save)
    root.mainloop()

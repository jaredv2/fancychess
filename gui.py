"""
gui.py  -  Fairy Chess  v4  (production)
=========================================
Architecture:
  Tkinter  : outer window + ALL UI controls (panel, buttons, move list, eval bar,
             material count tray, status)
  Pygame   : board rendering only (embedded via SDL_WINDOWID)

New in v4:
  - Board annotations  : right-click to highlight squares (orange/red/blue/green cycle)
                          right-click drag to draw arrows between squares
                          left-click on annotation to erase it
  - Board Setup window : enhanced with castling rights, en-passant, two-column layout
  - Mate-in-X (MX)     : prominently displayed in both eval bars in colour
  - Pack Manager v2    : "Create Pack" wizard, preview strip, Open Folder
  - Pack-aware images  : all piece images reload instantly when pack changes
"""

import sys, os, math, time, threading, json, shutil
sys.path.insert(0, os.path.dirname(__file__))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import pygame

from logic import Board, Piece, MoveGenerator, build_default_pieces
from ai    import get_best_move, quick_eval, ELO_LEVELS

print("[DEBUG gui] gui.py v4 loaded")

# ─────────────────────────────────────────────────────────────────────────────
# Layout constants
# ─────────────────────────────────────────────────────────────────────────────
CELL      = 80
BOARD_SZ  = 8 * CELL
EVAL_W    = 22
PANEL_W   = 370
FPS       = 60

# ─────────────────────────────────────────────────────────────────────────────
# Colours — board (pygame)
# ─────────────────────────────────────────────────────────────────────────────
SQ_LIGHT        = (235, 236, 208)
SQ_DARK         = ( 86, 125,  70)
SEL_COL         = (246, 246, 105, 160)
DOT_COL         = ( 20,  85,  30, 200)
CAP_COL         = (204,  34,  34)
LM_COL          = (246, 246, 105,  90)
CHK_COL         = (220,  36,  36, 160)
BG_COL          = ( 18,  18,  26)
COORD_ON_LIGHT  = ( 86, 125,  70)
COORD_ON_DARK   = (235, 236, 208)

# Annotation colours: right-click highlight cycle (RGBA)
ANNOT_COLORS = [
    (255, 165,  30, 180),   # orange
    (220,  50,  50, 180),   # red
    ( 50, 120, 220, 180),   # blue
    ( 50, 200,  90, 180),   # green
]
ARROW_BODY_W  = 10
ARROW_HEAD_SZ = 18

# ─────────────────────────────────────────────────────────────────────────────
# Colours — Tkinter dark theme
# ─────────────────────────────────────────────────────────────────────────────
TK_BG    = "#0D0D13"
TK_PANEL = "#12121C"
TK_SURF  = "#1A1A26"
TK_SURF2 = "#202030"
TK_BORD  = "#2A2A3E"
TK_TXT   = "#D0D0E0"
TK_DIM   = "#5F5F76"
TK_RED   = "#BE3232"
TK_GOLD  = "#CDA537"

ACCENTS = {
    "Gold":    "#CDA537",
    "Cyan":    "#32B9D2",
    "Violet":  "#9B5CE4",
    "Coral":   "#E46452",
    "Emerald": "#34AF73",
}

SYM_FILE = {
    "K": "king", "Q": "queen", "R": "rook",
    "B": "bishop", "N": "knight", "P": "pawn",
}
PIECE_CP = {"Q": 900, "R": 500, "B": 330, "N": 320, "P": 100, "K": 0}


def _font(size=10, bold=False, mono=False):
    if mono:
        return ("DejaVu Sans Mono", size)
    return ("Poppins", size, "bold") if bold else ("Poppins", size)


# ─────────────────────────────────────────────────────────────────────────────
# Asset loading — pack-aware
# ─────────────────────────────────────────────────────────────────────────────
_PACKS_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs.json")


def _load_packs_cfg():
    if os.path.isfile(_PACKS_CFG):
        try:
            with open(_PACKS_CFG) as f:
                return json.load(f)
        except Exception as e:
            print(f"[DEBUG gui] packs.json error: {e}")
    return {}


def _save_packs_cfg(cfg):
    try:
        with open(_PACKS_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        print("[DEBUG gui] packs.json saved")
    except Exception as e:
        print(f"[DEBUG gui] packs.json save error: {e}")


def _default_pack_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for base in [here, os.getcwd(), os.path.join(here, "..")]:
        p = os.path.join(base, "assets", "chessmat")
        if os.path.isdir(p):
            return p
    return None


def _get_active_root():
    cfg    = _load_packs_cfg()
    active = cfg.get("__active__", "")
    if active and active in cfg:
        path = cfg[active]
        if os.path.isdir(path):
            return path
    return _default_pack_root()


def load_images(size, pack_root=None):
    imgs = {}
    root = pack_root or _get_active_root()
    if not root:
        print("[DEBUG gui] no chessmat folder — shape fallback")
        return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path):
                continue
            try:
                raw = pygame.image.load(path).convert_alpha()
                imgs[(sym, owner)] = pygame.transform.smoothscale(raw, (size, size))
            except Exception as e:
                print(f"[DEBUG gui] load error {path}: {e}")
    print(f"[DEBUG gui] loaded {len(imgs)}/12 pygame images @ {size}px")
    return imgs


def load_tk_icons(size=32, pack_root=None):
    imgs = {}
    root = pack_root or _get_active_root()
    if not root:
        return imgs
    try:
        from PIL import Image as PilImg, ImageTk as PilTk
    except ImportError:
        print("[DEBUG gui] Pillow missing — tk icons unavailable")
        return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path):
                continue
            try:
                img = PilImg.open(path).convert("RGBA").resize((size, size), PilImg.LANCZOS)
                imgs[(sym, owner)] = PilTk.PhotoImage(img)
            except Exception as e:
                print(f"[DEBUG gui] tk icon error {path}: {e}")
    print(f"[DEBUG gui] loaded {len(imgs)}/12 tk icons @ {size}px")
    return imgs


# ─────────────────────────────────────────────────────────────────────────────
# Pygame drawing helpers
# ─────────────────────────────────────────────────────────────────────────────
def draw_piece(surf, imgs, piece, px, py, size=CELL, alpha=255, scale=1.0):
    key     = (piece.piece_type.symbol, piece.owner)
    img     = imgs.get(key)
    margin  = max(4, int(size * 0.07))
    draw_sz = max(4, int((size - margin * 2) * scale))
    cx = px + size // 2
    cy = py + size // 2
    if img:
        s = pygame.transform.smoothscale(img, (draw_sz, draw_sz))
        if alpha < 255:
            s = s.copy(); s.set_alpha(alpha)
        surf.blit(s, (cx - draw_sz // 2, cy - draw_sz // 2))
    else:
        col = (230, 225, 218) if piece.owner == 0 else (52, 48, 44)
        pygame.draw.circle(surf, col, (cx, cy), draw_sz // 2)
        pygame.draw.circle(surf, (80, 80, 100), (cx, cy), draw_sz // 2, 2)


def draw_arrow(surf, x1, y1, x2, y2, color):
    """Draw bold translucent arrow from (x1,y1) to (x2,y2) on surf."""
    dx = x2 - x1; dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 4:
        return
    nx = dx / dist; ny = dy / dist
    head_len = ARROW_HEAD_SZ
    # Shorten shaft so arrowhead doesn't overlap
    sx2 = x2 - nx * head_len; sy2 = y2 - ny * head_len
    tmp = pygame.Surface((BOARD_SZ, BOARD_SZ), pygame.SRCALPHA)
    pygame.draw.line(tmp, color, (int(x1), int(y1)), (int(sx2), int(sy2)), ARROW_BODY_W)
    perp_x = -ny; perp_y = nx
    hw = ARROW_HEAD_SZ * 0.55
    pts = [
        (int(x2), int(y2)),
        (int(sx2 + perp_x * hw), int(sy2 + perp_y * hw)),
        (int(sx2 - perp_x * hw), int(sy2 - perp_y * hw)),
    ]
    pygame.draw.polygon(tmp, color, pts)
    surf.blit(tmp, (0, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Animation classes
# ─────────────────────────────────────────────────────────────────────────────
class MovingPiece:
    SPEED = 9.0
    def __init__(self, piece, from_px, to_px):
        self.piece = piece
        self.fx, self.fy = from_px
        self.tx, self.ty = to_px
        self.t = 0.0; self.done = False

    def update(self, dt):
        self.t = min(1.0, self.t + dt * self.SPEED)
        if self.t >= 1.0: self.done = True

    @property
    def pos(self):
        e = 1.0 - (1.0 - self.t) ** 3
        return (self.fx + (self.tx - self.fx) * e, self.fy + (self.ty - self.fy) * e)


class FadePiece:
    SPEED = 5.5
    def __init__(self, piece, px, py):
        self.piece = piece; self.px = px; self.py = py
        self.t = 0.0; self.done = False

    def update(self, dt):
        self.t = min(1.0, self.t + dt * self.SPEED)
        if self.t >= 1.0: self.done = True

    @property
    def alpha(self): return int((1.0 - self.t) * 255)
    @property
    def scale(self): return 1.0 - self.t * 0.45


class ShakeAnim:
    def __init__(self, row, col, dur=0.38):
        self.row = row; self.col = col
        self.t = 0.0; self.dur = dur; self.done = False

    def update(self, dt):
        self.t += dt
        if self.t >= self.dur: self.done = True

    @property
    def offset(self):
        if self.done: return 0
        p = self.t / self.dur
        return int(math.sin(p * math.pi * 6) * 7 * (1.0 - p))


class MatePulse:
    def __init__(self, row, col):
        self.row = row; self.col = col; self.t = 0.0

    def update(self, dt): self.t += dt

    @property
    def alpha(self): return int(abs(math.sin(self.t * 3.0)) * 185)


class DrawFlash:
    def __init__(self, dur=1.2):
        self.t = 0.0; self.dur = dur; self.done = False

    def update(self, dt):
        self.t += dt
        if self.t >= self.dur: self.done = True

    @property
    def alpha(self):
        p = self.t / self.dur
        return int(math.sin(p * math.pi) * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Pack Manager modal  (v4)
# ─────────────────────────────────────────────────────────────────────────────
class PackManagerWindow(tk.Toplevel):
    """
    Manage piece image packs.
    A pack folder must contain white/ and black/ subdirs with PNGs:
      king, queen, rook, bishop, knight, pawn

    v4 additions:
      - "Create Pack" wizard: copies default pack to new folder, registers it
      - Preview strip: 12 coloured dots showing which PNGs exist
      - "Open Folder" button to reveal in file manager
    """
    def __init__(self, master, on_pack_reload=None):
        super().__init__(master)
        self.title("Piece Pack Manager")
        self.configure(bg=TK_BG)
        self.resizable(False, False)
        self.grab_set()
        self._on_pack_reload = on_pack_reload
        self._cfg = _load_packs_cfg()
        self._build()
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width()  - self.winfo_width())  // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")
        print("[DEBUG gui] PackManagerWindow v4 opened")

    def _build(self):
        BS = dict(bg=TK_SURF2, fg=TK_TXT, relief="flat", font=_font(10),
                  padx=8, pady=4, cursor="hand2",
                  activebackground=TK_SURF, activeforeground=TK_TXT, bd=0)
        F = tk.Frame(self, bg=TK_BG, padx=18, pady=16)
        F.pack(fill="both", expand=True)

        tk.Label(F, text="Piece Image Packs", bg=TK_BG, fg=TK_TXT,
                 font=_font(13, bold=True)).pack(anchor="w", pady=(0, 3))
        tk.Label(F, text="Pack folder must contain  white/  and  black/  subdirectories\n"
                         "with PNG files named: king  queen  rook  bishop  knight  pawn",
                 bg=TK_BG, fg=TK_DIM, font=_font(9), justify="left").pack(anchor="w", pady=(0, 10))

        # List
        lf = tk.Frame(F, bg=TK_SURF, bd=0, highlightthickness=1, highlightbackground=TK_BORD)
        lf.pack(fill="x", pady=(0, 6))
        sb = tk.Scrollbar(lf, orient="vertical")
        self._lb = tk.Listbox(lf, yscrollcommand=sb.set, height=7,
                              bg=TK_SURF, fg=TK_TXT, selectbackground=TK_SURF2,
                              selectforeground=TK_GOLD, font=_font(10), relief="flat",
                              bd=0, activestyle="none", highlightthickness=0, exportselection=False)
        sb.config(command=self._lb.yview)
        sb.pack(side="right", fill="y")
        self._lb.pack(side="left", fill="both", expand=True)
        self._lb.bind("<<ListboxSelect>>", self._on_sel)
        self._refresh_list()

        # Path hint
        self._path_var = tk.StringVar(value="")
        tk.Label(F, textvariable=self._path_var, bg=TK_BG, fg=TK_DIM,
                 font=_font(8), anchor="w", wraplength=440).pack(fill="x", pady=(0, 2))

        # Preview strip (12 slots)
        self._prev_cv = tk.Canvas(F, bg=TK_BG, height=20, highlightthickness=0)
        self._prev_cv.pack(fill="x", pady=(0, 10))

        # Buttons row 1
        br1 = tk.Frame(F, bg=TK_BG)
        br1.pack(fill="x", pady=(0, 4))
        tk.Button(br1, text="Add Folder...", command=self._add,
                  **dict(BS, bg="#142A1A", fg="#70D890")).pack(side="left", padx=(0,4))
        tk.Button(br1, text="Create Pack...", command=self._create_pack,
                  **dict(BS, bg="#1A2A1A", fg="#90E8A0")).pack(side="left", padx=(0,4))
        tk.Button(br1, text="Remove", command=self._remove,
                  **dict(BS, bg="#2E0E0E", fg="#E08080")).pack(side="left", padx=(0,4))
        tk.Button(br1, text="Open Folder", command=self._open_folder,
                  **dict(BS, bg="#222232", fg="#9090C0")).pack(side="left")

        # Buttons row 2
        br2 = tk.Frame(F, bg=TK_BG)
        br2.pack(fill="x")
        tk.Button(br2, text="Use Selected", command=self._use_selected,
                  **dict(BS, bg="#1A1A3A", fg="#80A8E8")).pack(side="left", padx=(0,4))
        tk.Button(br2, text="Use Default", command=self._use_default,
                  **BS).pack(side="left", padx=(0,4))
        tk.Button(br2, text="Close", command=self.destroy, **BS).pack(side="right")

    def _pack_names(self):
        return [k for k in self._cfg if not k.startswith("__")]

    def _refresh_list(self):
        active = self._cfg.get("__active__", "")
        self._lb.delete(0, "end")
        default_root = _default_pack_root()
        ok_d = "OK " if default_root and os.path.isdir(default_root) else "ERR"
        self._lb.insert("end", f"  [{ok_d}]  Default (assets/chessmat)")
        for name in self._pack_names():
            path = self._cfg[name]
            ok   = "OK " if (os.path.isdir(os.path.join(path, "white")) and
                             os.path.isdir(os.path.join(path, "black"))) else "ERR"
            star = " *" if name == active else "  "
            self._lb.insert("end", f"  [{ok}]{star} {name}")
        print(f"[DEBUG packs] list refreshed, {len(self._pack_names())} packs")

    def _on_sel(self, _=None):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx == 0:
            root = _default_pack_root()
            self._path_var.set(f"Path: {root or '(not found)'}")
            self._draw_preview(root)
        else:
            names = self._pack_names()
            if idx - 1 < len(names):
                path = self._cfg[names[idx - 1]]
                self._path_var.set(f"Path: {path}")
                self._draw_preview(path)

    def _draw_preview(self, folder):
        """Show 12 coloured slots: green=PNG found, red=missing."""
        c = self._prev_cv
        c.delete("all")
        if not folder: return
        names = ["king","queen","rook","bishop","knight","pawn"]
        x = 4
        for sub in ["white", "black"]:
            for pn in names:
                exists = os.path.isfile(os.path.join(folder, sub, f"{pn}.png"))
                fill = "#50C870" if exists else "#503030"
                c.create_rectangle(x, 2, x+18, 18, fill=fill, outline="")
                c.create_text(x+9, 10, text=pn[0].upper(), fill="#DDDDDD" if exists else "#885555",
                              font=_font(6, bold=True))
                x += 22
            x += 8  # gap between W / B groups
        c.create_text(x, 10, text="green=found  red=missing", fill=TK_DIM, font=_font(7), anchor="w")
        print(f"[DEBUG packs] preview for {folder}")

    def _add(self):
        folder = filedialog.askdirectory(title="Select pack folder", parent=self)
        if not folder: return
        has_w = os.path.isdir(os.path.join(folder, "white"))
        has_b = os.path.isdir(os.path.join(folder, "black"))
        if not (has_w and has_b):
            messagebox.showerror("Invalid Pack",
                "Folder must contain 'white' and 'black' subdirectories.", parent=self)
            return
        found = sum(1 for sub in ["white","black"]
                    for f in ["king","queen","rook","bishop","knight","pawn"]
                    if os.path.isfile(os.path.join(folder, sub, f"{f}.png")))
        name = os.path.basename(folder); base = name; i = 2
        while name in self._cfg: name = f"{base}_{i}"; i += 1
        self._cfg[name] = folder
        _save_packs_cfg(self._cfg)
        self._refresh_list()
        messagebox.showinfo("Pack Added", f"Pack '{name}' added.\n{found}/12 images found.", parent=self)
        print(f"[DEBUG packs] added '{name}' -> {folder}")

    def _create_pack(self):
        """
        Wizard: ask for name + parent folder, create subfolders,
        copy default pack PNGs as starter, register in packs.json.
        """
        pack_name = simpledialog.askstring("Create Pack", "Enter a name for the new pack:", parent=self)
        if not pack_name or not pack_name.strip(): return
        pack_name = pack_name.strip()
        if pack_name in self._cfg:
            messagebox.showerror("Name Taken", f"A pack named '{pack_name}' already exists.", parent=self)
            return
        dest_parent = filedialog.askdirectory(
            title=f"Choose parent folder — '{pack_name}' subfolder will be created inside it",
            parent=self)
        if not dest_parent: return
        dest = os.path.join(dest_parent, pack_name)
        try:
            os.makedirs(os.path.join(dest, "white"), exist_ok=True)
            os.makedirs(os.path.join(dest, "black"), exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create folders:\n{e}", parent=self)
            return
        # Copy default pack as starter files
        src_root = _default_pack_root(); copied = 0
        if src_root:
            for sub in ["white", "black"]:
                for pn in ["king","queen","rook","bishop","knight","pawn"]:
                    src = os.path.join(src_root, sub, f"{pn}.png")
                    dst = os.path.join(dest, sub, f"{pn}.png")
                    if os.path.isfile(src) and not os.path.isfile(dst):
                        try: shutil.copy2(src, dst); copied += 1
                        except Exception as e: print(f"[DEBUG packs] copy error: {e}")
        self._cfg[pack_name] = dest
        _save_packs_cfg(self._cfg)
        self._refresh_list()
        messagebox.showinfo("Pack Created",
            f"Pack '{pack_name}' created at:\n{dest}\n\n"
            f"{copied}/12 starter images copied from default pack.\n\n"
            "Replace the PNG files with your own artwork, then click 'Use Selected'.",
            parent=self)
        print(f"[DEBUG packs] created '{pack_name}' at {dest}, copied {copied} files")

    def _remove(self):
        sel = self._lb.curselection()
        if not sel or sel[0] == 0: return
        names = self._pack_names(); idx = sel[0] - 1
        if idx < len(names):
            name = names[idx]
            if not messagebox.askyesno("Remove Pack",
                    f"Remove '{name}' from list?\n(Files will NOT be deleted)", parent=self):
                return
            if self._cfg.get("__active__") == name: self._cfg["__active__"] = ""
            del self._cfg[name]
            _save_packs_cfg(self._cfg)
            self._refresh_list()
            self._prev_cv.delete("all")
            print(f"[DEBUG packs] removed '{name}'")

    def _open_folder(self):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        folder = _default_pack_root() if idx == 0 else self._cfg.get(
            self._pack_names()[idx-1] if idx-1 < len(self._pack_names()) else "", "")
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Open Folder", "Folder not found.", parent=self); return
        try:
            if sys.platform == "win32": os.startfile(folder)
            elif sys.platform == "darwin": os.system(f'open "{folder}"')
            else: os.system(f'xdg-open "{folder}"')
        except Exception as e:
            print(f"[DEBUG packs] open folder error: {e}")

    def _use_selected(self):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx == 0: self._use_default(); return
        names = self._pack_names()
        if idx - 1 < len(names):
            name = names[idx - 1]
            self._cfg["__active__"] = name
            _save_packs_cfg(self._cfg)
            self._refresh_list()
            if self._on_pack_reload: self._on_pack_reload()
            messagebox.showinfo("Pack Active", f"Now using pack: {name}", parent=self)
            print(f"[DEBUG packs] activated '{name}'")

    def _use_default(self):
        self._cfg["__active__"] = ""
        _save_packs_cfg(self._cfg)
        self._refresh_list()
        if self._on_pack_reload: self._on_pack_reload()
        messagebox.showinfo("Default Pack", "Now using default piece images.", parent=self)
        print("[DEBUG packs] using default pack")


# ─────────────────────────────────────────────────────────────────────────────
# Board Setup window  (v4)
# ─────────────────────────────────────────────────────────────────────────────
class BoardEditWindow(tk.Toplevel):
    """
    Visual board editor.
    v4: two-column layout, castling rights checkboxes, en-passant file selector,
        larger 72px cells, coordinate margin, Quick-fill buttons.
    """
    CELL = 72

    def __init__(self, master, board, piece_types, tk_icons, accent, on_apply):
        super().__init__(master)
        self.title("Board Setup")
        self.configure(bg=TK_BG)
        self.resizable(False, False)
        self.grab_set()
        self._work_board  = board.clone()
        self._piece_types = piece_types
        self._tk_icons    = tk_icons
        self._accent      = accent
        self._on_apply    = on_apply
        self._sel         = None
        self._palette_pos = []
        self._img_refs    = []
        self._board_img_refs = []
        self._stm_var   = tk.IntVar(value=board.current_player)
        self._castle_WK = tk.BooleanVar(value=True)
        self._castle_WQ = tk.BooleanVar(value=True)
        self._castle_BK = tk.BooleanVar(value=True)
        self._castle_BQ = tk.BooleanVar(value=True)
        self._ep_var    = tk.StringVar(value="-")
        self._build()
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width()  - self.winfo_width())  // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")
        print("[DEBUG board_edit] v4 opened")

    def _build(self):
        C  = self.CELL
        BS = dict(bg=TK_SURF2, fg=TK_TXT, relief="flat", font=_font(10),
                  padx=10, pady=4, cursor="hand2",
                  activebackground=TK_SURF, activeforeground=TK_TXT, bd=0)
        outer = tk.Frame(self, bg=TK_BG, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="Board Setup", bg=TK_BG, fg=TK_TXT,
                 font=_font(13, bold=True)).pack(anchor="w", pady=(0,2))
        tk.Label(outer, text="Left-click palette piece  ->  click square to place    "
                             "Right-click square to erase piece",
                 bg=TK_BG, fg=TK_DIM, font=_font(9)).pack(anchor="w", pady=(0,8))

        row_frame = tk.Frame(outer, bg=TK_BG)
        row_frame.pack(fill="both", expand=True)

        left = tk.Frame(row_frame, bg=TK_BG)
        left.pack(side="left", fill="y", padx=(0,12))

        right = tk.Frame(row_frame, bg=TK_BG)
        right.pack(side="left", fill="both")

        # ── Left: Palette ──────────────────────────────────────────────────────
        tk.Label(left, text="PALETTE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        self._pal = tk.Canvas(left, bg=TK_SURF, highlightthickness=1,
                              highlightbackground=TK_BORD)
        self._pal.pack(anchor="w", pady=(2,12))
        self._pal.bind("<Button-1>", self._pal_click)

        # Side to move
        tk.Label(left, text="SIDE TO MOVE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        stm_r = tk.Frame(left, bg=TK_BG)
        stm_r.pack(anchor="w", pady=(0,10))
        for lbl, val in [("White", 0), ("Black", 1)]:
            tk.Radiobutton(stm_r, text=lbl, variable=self._stm_var, value=val,
                           bg=TK_BG, fg=TK_TXT, selectcolor=TK_SURF2,
                           activebackground=TK_BG, font=_font(10)).pack(side="left", padx=(0,10))

        # Castling rights
        tk.Label(left, text="CASTLING RIGHTS", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        cf = tk.Frame(left, bg=TK_BG)
        cf.pack(anchor="w", pady=(0,10))
        opts = [("White O-O", self._castle_WK), ("White O-O-O", self._castle_WQ),
                ("Black O-O", self._castle_BK), ("Black O-O-O", self._castle_BQ)]
        for i, (lbl, var) in enumerate(opts):
            tk.Checkbutton(cf, text=lbl, variable=var, bg=TK_BG, fg=TK_TXT,
                           selectcolor=TK_SURF2, activebackground=TK_BG,
                           font=_font(9), cursor="hand2"
                           ).grid(row=i//2, column=i%2, sticky="w", padx=(0,8))

        # En-passant
        tk.Label(left, text="EN PASSANT FILE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        ttk.Combobox(left, textvariable=self._ep_var, state="readonly",
                     values=["-","a","b","c","d","e","f","g","h"],
                     font=_font(10), width=6).pack(anchor="w", pady=(0,12))

        # Quick fill
        tk.Label(left, text="QUICK FILL", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        tk.Button(left, text="Standard Start", command=self._reset,
                  **dict(BS, bg="#1A2A3A", fg="#80B0D8")).pack(fill="x", pady=2)
        tk.Button(left, text="Clear All", command=self._clear,
                  **dict(BS, bg="#2E0E0E", fg="#E08080")).pack(fill="x", pady=2)

        tk.Frame(left, bg=TK_BORD, height=1).pack(fill="x", pady=8)
        tk.Button(left, text="Apply Position", command=self._apply,
                  **dict(BS, bg="#142A1A", fg="#70D890")).pack(fill="x", pady=2)
        tk.Button(left, text="Cancel", command=self.destroy, **BS).pack(fill="x", pady=2)

        # ── Right: Board canvas ────────────────────────────────────────────────
        MARGIN = 22
        board_w = C * 8 + MARGIN
        board_h = C * 8 + MARGIN
        self._bc = tk.Canvas(right, width=board_w, height=board_h,
                             bg="#101018", highlightthickness=1, highlightbackground=TK_BORD)
        self._bc.pack()
        self._bc.bind("<Button-1>",  self._bc_left)
        self._bc.bind("<Button-3>",  self._bc_right)
        self._MARGIN = MARGIN

        self._draw_palette()
        self._draw_board()

    # ── Palette ───────────────────────────────────────────────────────────────
    def _draw_palette(self):
        C = self.CELL; GAP = 4
        names = list(self._piece_types.keys())
        ncols = max(len(names), 1)
        self._pal.config(width=ncols*(C+GAP)+GAP, height=2*(C+GAP)+GAP)
        self._pal.delete("all"); self._palette_pos.clear(); self._img_refs.clear()
        for oi, owner in enumerate([0,1]):
            for ci, name in enumerate(names):
                pt = self._piece_types[name]; sym = pt.symbol
                x = GAP + ci*(C+GAP); y = GAP + oi*(C+GAP)
                sel = (self._sel == (name, owner))
                self._pal.create_rectangle(x, y, x+C, y+C,
                    fill="#3A2808" if sel else TK_SURF2,
                    outline=self._accent if sel else TK_BORD, width=2)
                img = self._tk_icons.get((sym, owner))
                if img:
                    self._img_refs.append(img)
                    self._pal.create_image(x+C//2, y+C//2, image=img, anchor="center")
                else:
                    fc = "#D0CCC0" if owner == 0 else "#302C28"
                    self._pal.create_oval(x+8, y+8, x+C-8, y+C-8, fill=fc, outline="")
                    self._pal.create_text(x+C//2, y+C//2, text=sym,
                        fill="#181818" if owner==0 else "#D8D8D8", font=_font(15, bold=True))
                self._pal.create_text(x+C-5, y+5, text="W" if owner==0 else "B",
                    anchor="ne", fill=TK_DIM, font=_font(7))
                self._palette_pos.append((name, owner, x, y))
        print(f"[DEBUG board_edit] palette drawn: {len(self._palette_pos)} cells")

    def _pal_click(self, event):
        C = self.CELL; GAP = 4
        for (name, owner, x, y) in self._palette_pos:
            if x <= event.x < x+C and y <= event.y < y+C:
                self._sel = None if self._sel == (name, owner) else (name, owner)
                self._draw_palette(); return
        self._sel = None; self._draw_palette()

    # ── Board canvas ──────────────────────────────────────────────────────────
    def _draw_board(self):
        C = self.CELL; M = self._MARGIN
        self._bc.delete("all"); self._board_img_refs = []
        # Colourful board: warm light / rich green dark
        SQ_L = "#E8EAD0"; SQ_D = "#5A8C4E"
        for row in range(8):
            for col in range(8):
                x = M + col * C; y = (7 - row) * C
                lt = (row + col) % 2 == 0
                self._bc.create_rectangle(x, y, x+C, y+C,
                    fill=SQ_L if lt else SQ_D, outline="")
                # Rank labels on left
                if col == 0:
                    self._bc.create_text(M//2, y+C//2, text=str(row+1),
                        anchor="center", fill="#A0A8B8", font=_font(8, bold=True))
                # File labels on bottom
                if row == 0:
                    self._bc.create_text(x+C//2, 8*C+M//2, text="abcdefgh"[col],
                        anchor="center", fill="#A0A8B8", font=_font(8, bold=True))
                # Piece
                p = self._work_board.get(row, col)
                if p:
                    sym = p.piece_type.symbol
                    img = self._tk_icons.get((sym, p.owner))
                    if img:
                        self._board_img_refs.append(img)
                        self._bc.create_image(x+C//2, y+C//2, image=img, anchor="center")
                    else:
                        fc2 = "#E8E4DC" if p.owner == 0 else "#2A2826"
                        self._bc.create_oval(x+5, y+5, x+C-5, y+C-5,
                            fill=fc2, outline="#808090", width=2)
                        self._bc.create_text(x+C//2, y+C//2, text=sym,
                            fill="#181818" if p.owner==0 else "#D8D8D8",
                            font=_font(15, bold=True))

    def _bc_coords(self, event):
        C = self.CELL; M = self._MARGIN
        col = (event.x - M) // C
        row = 7 - event.y // C
        return row, col

    def _bc_left(self, event):
        if not self._sel: return
        row, col = self._bc_coords(event)
        if not (0 <= row < 8 and 0 <= col < 8): return
        name, owner = self._sel
        pt = self._piece_types.get(name)
        if pt:
            self._work_board.grid[row][col] = None
            self._work_board.place(Piece(pt, owner, row, col))
            print(f"[DEBUG board_edit] placed {name} at ({row},{col})")
        self._draw_board()

    def _bc_right(self, event):
        row, col = self._bc_coords(event)
        if 0 <= row < 8 and 0 <= col < 8:
            self._work_board.grid[row][col] = None
            print(f"[DEBUG board_edit] erased ({row},{col})")
        self._draw_board()

    def _reset(self):
        self._work_board = Board(8, 8)
        pt = self._piece_types
        order = ["Rook","Knight","Bishop","Queen","King","Bishop","Knight","Rook"]
        for c, name in enumerate(order):
            if name in pt:
                self._work_board.place(Piece(pt[name], 0, 0, c))
                self._work_board.place(Piece(pt[name], 1, 7, c))
        for c in range(8):
            if "Pawn" in pt:
                self._work_board.place(Piece(pt["Pawn"], 0, 1, c))
                self._work_board.place(Piece(pt["Pawn"], 1, 6, c))
        self._draw_board()
        print("[DEBUG board_edit] reset to standard start")

    def _clear(self):
        for r in range(8):
            for c in range(8):
                self._work_board.grid[r][c] = None
        self._draw_board()
        print("[DEBUG board_edit] cleared")

    def _apply(self):
        self._work_board.current_player = self._stm_var.get()
        self._on_apply(self._work_board)
        self.destroy()
        print("[DEBUG board_edit] position applied")


# ─────────────────────────────────────────────────────────────────────────────
# Material Tray widget
# ─────────────────────────────────────────────────────────────────────────────
class MaterialTray(tk.Canvas):
    ICON = 20; PAD = 3

    def __init__(self, master, **kw):
        row_h = self.ICON + 6
        super().__init__(master, bg=TK_PANEL, height=row_h*2+20, highlightthickness=0, **kw)
        self._tk_icons = {}; self._cap_white = []; self._cap_black = []; self._img_refs = []
        print("[DEBUG material] MaterialTray created")

    def set_icons(self, icons): self._tk_icons = icons

    def refresh(self, board, initial_counts=None):
        if initial_counts is None:
            initial_counts = {}
            for sym in ["K","Q","R","B","N","P"]:
                cnt = {"K":1,"Q":1,"R":2,"B":2,"N":2,"P":8}[sym]
                initial_counts[(sym, 0)] = cnt; initial_counts[(sym, 1)] = cnt
        on_board = {}
        for p in board.all_pieces():
            k = (p.piece_type.symbol, p.owner)
            on_board[k] = on_board.get(k, 0) + 1
        self._cap_white = []; self._cap_black = []
        for (sym, owner), sc in initial_counts.items():
            missing = max(0, sc - on_board.get((sym, owner), 0))
            if owner == 1: self._cap_white.extend([sym]*missing)
            else:          self._cap_black.extend([sym]*missing)
        key = lambda s: -PIECE_CP.get(s, 0)
        self._cap_white.sort(key=key); self._cap_black.sort(key=key)
        self._redraw()
        print(f"[DEBUG material] w_caps={self._cap_white}  b_caps={self._cap_black}")

    def _redraw(self):
        self.delete("all"); self._img_refs.clear()
        ISZ = self.ICON; PAD = self.PAD; row_h = ISZ + 6
        def cp_sum(syms): return sum(PIECE_CP.get(s, 0) for s in syms)
        adv_w = cp_sum(self._cap_white) - cp_sum(self._cap_black)
        for row_idx, (caps, owner, label) in enumerate([
            (self._cap_white, 1, "White takes"), (self._cap_black, 0, "Black takes")]):
            base_y = row_idx * (row_h + 10)
            self.create_text(4, base_y+2, text=label, anchor="nw", fill=TK_DIM, font=_font(7))
            icon_y = base_y + 13; x = 4
            for sym in caps:
                img = self._tk_icons.get((sym, owner))
                if img:
                    self._img_refs.append(img)
                    self.create_image(x+ISZ//2, icon_y+ISZ//2, image=img, anchor="center")
                else:
                    fc = "#C8C4BE" if owner==0 else "#383634"
                    self.create_oval(x, icon_y, x+ISZ, icon_y+ISZ, fill=fc, outline="")
                    self.create_text(x+ISZ//2, icon_y+ISZ//2, text=sym,
                        fill="#181818" if owner==0 else "#D8D8D8", font=_font(7, bold=True))
                x += ISZ + PAD
            if row_idx == 0 and adv_w > 50:
                self.create_text(x+4, icon_y+ISZ//2, anchor="w",
                    text=f"+{adv_w//100}", fill=TK_GOLD, font=_font(8, bold=True))
            elif row_idx == 1 and adv_w < -50:
                self.create_text(x+4, icon_y+ISZ//2, anchor="w",
                    text=f"+{-adv_w//100}", fill=TK_GOLD, font=_font(8, bold=True))


# ─────────────────────────────────────────────────────────────────────────────
# Tkinter panel
# ─────────────────────────────────────────────────────────────────────────────
class ChessPanel(tk.Frame):
    def __init__(self, master, game, **kw):
        super().__init__(master, bg=TK_PANEL, width=PANEL_W, **kw)
        self.game = game; self.pack_propagate(False)
        self._accent_var = tk.StringVar(value="Gold")
        self._ml_tags = []; self._eval_score = 0; self._eval_mate = None; self._eval_result = None
        self._build()

    def _btn(self, parent, text, cmd, bg=TK_SURF2, fg=TK_TXT, **kw):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, relief="flat", bd=0,
                      activebackground=TK_SURF, activeforeground=TK_TXT,
                      font=_font(10), padx=8, pady=5, cursor="hand2", **kw)
        b.bind("<Enter>", lambda e: b.config(bg=TK_SURF))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _sep(self):   tk.Frame(self, bg=TK_BORD, height=1).pack(fill="x", padx=10, pady=5)
    def _sec(self, t): tk.Label(self, text=t, bg=TK_PANEL, fg=TK_DIM, font=_font(9)).pack(anchor="w", padx=12, pady=(6,1))

    def _build(self):
        PAD = dict(padx=10, pady=2)
        self._sec("GAME MODE")
        self.mode_var = tk.StringVar(value="Human vs AI")
        mode_cb = ttk.Combobox(self, textvariable=self.mode_var, state="readonly",
                               values=["Human vs Human","Human vs AI","AI vs AI"], font=_font(10))
        mode_cb.pack(fill="x", **PAD)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.game.on_mode_change())

        self._sec("AI STRENGTH")
        self.elo_var = tk.StringVar()
        elo_opts = [f"Elo {p['elo']}  {p['name']}" for p in ELO_LEVELS]
        self.elo_var.set(elo_opts[4])
        elo_cb = ttk.Combobox(self, textvariable=self.elo_var, state="readonly", values=elo_opts, font=_font(10))
        elo_cb.pack(fill="x", **PAD)

        self._sec("ACCENT")
        theme_cb = ttk.Combobox(self, textvariable=self._accent_var, state="readonly",
                                values=list(ACCENTS.keys()), font=_font(10))
        theme_cb.pack(fill="x", **PAD)
        theme_cb.bind("<<ComboboxSelected>>", lambda e: self.game.on_accent_change())

        self._sep()

        r1 = tk.Frame(self, bg=TK_PANEL); r1.pack(fill="x", padx=10, pady=2)
        self._btn(r1,"New Game", self.game.new_game ).pack(side="left",expand=True,fill="x",padx=(0,2))
        self._btn(r1,"Undo",     self.game.undo      ).pack(side="left",expand=True,fill="x",padx=(2,2))
        self._btn(r1,"Edit Pieces", self.game.open_editor).pack(side="left",expand=True,fill="x",padx=(2,0))

        r2 = tk.Frame(self, bg=TK_PANEL); r2.pack(fill="x", padx=10, pady=2)
        self._btn(r2,"Board Setup", self.game.open_board_edit,
                  bg="#1A1A32",fg="#88AAEE").pack(side="left",expand=True,fill="x",padx=(0,2))
        self._btn(r2,"Packs",       self.game.open_packs,
                  bg="#1A1A32",fg="#88AAEE").pack(side="left",expand=True,fill="x",padx=(2,2))
        self._btn(r2,"Flip (F)",    self.game.flip_board,
                  bg="#1A1A32",fg="#88AAEE").pack(side="left",expand=True,fill="x",padx=(2,0))

        r3 = tk.Frame(self, bg=TK_PANEL); r3.pack(fill="x", padx=10, pady=2)
        for lbl, cmd in [("|<", lambda: self.game.go_to(0)), ("<", self.game.go_prev),
                         (">", self.game.go_next), (">|", self.game.go_last)]:
            self._btn(r3, lbl, cmd, bg=TK_SURF).pack(side="left",expand=True,fill="x",padx=1)

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = tk.Label(self, textvariable=self.status_var,
                                   bg=TK_PANEL, fg=TK_TXT, font=_font(10, bold=True))
        self.status_lbl.pack(fill="x", padx=10, pady=(4,0))

        self._sep()
        self._sec("EVALUATION")
        eval_row = tk.Frame(self, bg=TK_PANEL)
        eval_row.pack(fill="x", padx=10, pady=(0,2))
        self.eval_canvas = tk.Canvas(eval_row, height=24, bg=TK_SURF2, highlightthickness=0)
        self.eval_canvas.pack(side="left", fill="x", expand=True)
        self.eval_canvas.bind("<Configure>", lambda e: self._redraw_eval())
        self._badge_var = tk.StringVar(value="")
        self._badge_lbl = tk.Label(eval_row, textvariable=self._badge_var,
                                   bg=TK_PANEL, fg=TK_GOLD, font=_font(10, bold=True), width=5)
        self._badge_lbl.pack(side="left", padx=(4,0))

        self._sep()
        self._sec("MATERIAL")
        self.material = MaterialTray(self)
        self.material.pack(fill="x", padx=10, pady=(0,4))

        self._sep()
        tk.Label(self, text="Right-click: highlight square   Drag: draw arrow   Left-click: erase",
                 bg=TK_PANEL, fg=TK_DIM, font=_font(8), wraplength=PANEL_W-20).pack(fill="x", padx=10, pady=(0,2))

        self._sec("MOVES")
        ml_f = tk.Frame(self, bg=TK_PANEL)
        ml_f.pack(fill="both", expand=True, padx=10, pady=(0,6))
        scr = tk.Scrollbar(ml_f, orient="vertical")
        self.movelist = tk.Listbox(ml_f, yscrollcommand=scr.set,
                                   bg=TK_SURF, fg=TK_TXT, selectbackground=TK_SURF2,
                                   selectforeground=TK_TXT, font=_font(10, mono=True),
                                   relief="flat", bd=0, activestyle="none",
                                   highlightthickness=0, exportselection=False)
        scr.config(command=self.movelist.yview)
        scr.pack(side="right", fill="y"); self.movelist.pack(side="left",fill="both",expand=True)
        self.movelist.bind("<<ListboxSelect>>", self._on_ml_click)
        tk.Label(self, text="Arrow keys or click move to navigate  |  F = flip board",
                 bg=TK_PANEL, fg=TK_DIM, font=_font(8)).pack(pady=(0,6))

        self.mode_cb = mode_cb; self.elo_cb = elo_cb

    def set_status(self, text, color=TK_TXT):
        self.status_var.set(text); self.status_lbl.config(fg=color)

    def set_eval(self, score, mate=None, result=None):
        """
        score  : centipawns (+white, -black)
        mate   : int (+white mates in N, -black mates in N), or None
        result : "1-0"/"0-1"/"1/2"/None
        """
        self._eval_score = score; self._eval_mate = mate; self._eval_result = result
        self._redraw_eval(); self._update_badge()
        print(f"[DEBUG panel] eval score={score} mate={mate} result={result}")

    def _update_badge(self):
        result = self._eval_result; mate = self._eval_mate
        if result:
            self._badge_var.set(result)
            colour = TK_GOLD if result in ("1-0","0-1") else TK_DIM
        elif mate is not None:
            self._badge_var.set(f"M{abs(mate)}")
            colour = "#50E080" if mate > 0 else "#E05050"
        else:
            self._badge_var.set(""); colour = TK_DIM
        self._badge_lbl.config(fg=colour)

    def _redraw_eval(self):
        c = self.eval_canvas; w = c.winfo_width() or (PANEL_W-30); h = 24
        c.delete("all")
        sc = max(-2000, min(2000, self._eval_score))
        split = int(w * (0.5 - sc / 4000.0))
        c.create_rectangle(0, 0, split, h, fill="#232323", outline="")
        c.create_rectangle(split, 0, w, h,  fill="#CCCCCC", outline="")
        if self._eval_result:
            etxt = self._eval_result; edark = "#AAAAAA"; elight = "#444444"
        elif self._eval_mate is not None:
            etxt  = f"M{abs(self._eval_mate)}"
            edark  = "#FF8888" if self._eval_mate < 0 else "#88FF88"
            elight = "#CC4444" if self._eval_mate < 0 else "#228822"
        else:
            val = self._eval_score / 100.0
            etxt = f"+{val:.1f}" if val > 0 else f"{val:.1f}"
            edark = "#AAAAAA"; elight = "#444444"
        if split > w // 2:
            c.create_text(6, h//2, text=etxt, anchor="w", fill=edark, font=_font(8, bold=True))
        else:
            c.create_text(w-6, h//2, text=etxt, anchor="e", fill=elight, font=_font(8, bold=True))

    def update_movelist(self, san_rec, cursor, result_badge=""):
        self.movelist.delete(0, "end"); self._ml_tags = []; i = 0
        while i < len(san_rec):
            n = i//2+1; w = san_rec[i] if i < len(san_rec) else ""; b = san_rec[i+1] if i+1 < len(san_rec) else ""
            row_txt = f"  {n:>3}.  {w:<10}  {b}"
            if result_badge and i+2 >= len(san_rec): row_txt = row_txt.rstrip() + f"   {result_badge}"
            self.movelist.insert("end", row_txt); self._ml_tags.append(i+1); i += 2
        cur_row = max(0, (cursor-1)//2)
        if cur_row < self.movelist.size():
            self.movelist.selection_clear(0,"end"); self.movelist.selection_set(cur_row); self.movelist.see(cur_row)
        print(f"[DEBUG panel] movelist {len(san_rec)} moves cursor={cursor}")

    def _on_ml_click(self, ev):
        sel = self.movelist.curselection()
        if not sel: return
        idx = sel[0]; tag = self._ml_tags[idx] if idx < len(self._ml_tags) else idx*2+1
        self.game.go_to(tag)

    def get_mode(self):       return self.mode_var.get()
    def get_accent_hex(self): return ACCENTS.get(self._accent_var.get(), TK_GOLD)
    def get_accent_rgb(self):
        h = self.get_accent_hex().lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0,2,4))
    def get_elo_idx(self):
        val = self.elo_var.get()
        for i, p in enumerate(ELO_LEVELS):
            if str(p["elo"]) in val: return i
        return 4

    @staticmethod
    def apply_theme(root):
        style = ttk.Style(root); style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=TK_SURF2, background=TK_SURF2,
            foreground=TK_TXT, selectbackground=TK_SURF2, selectforeground=TK_TXT,
            bordercolor=TK_BORD, lightcolor=TK_BORD, darkcolor=TK_BORD, arrowcolor=TK_DIM)
        style.map("TCombobox",
            fieldbackground=[("readonly", TK_SURF2)], selectbackground=[("readonly", TK_SURF2)],
            selectforeground=[("readonly", TK_TXT)])
        style.configure("TScrollbar", background=TK_SURF2, troughcolor=TK_SURF,
            bordercolor=TK_SURF, arrowcolor=TK_DIM)


# ─────────────────────────────────────────────────────────────────────────────
# Board canvas frame
# ─────────────────────────────────────────────────────────────────────────────
class BoardCanvas(tk.Frame):
    def __init__(self, master, game, **kw):
        super().__init__(master, width=BOARD_SZ+EVAL_W+4, height=BOARD_SZ, bg=TK_BG, **kw)
        self.game = game; self.pack_propagate(False)

        self._embed = tk.Frame(self, width=BOARD_SZ, height=BOARD_SZ, bg="black")
        self._embed.place(x=0, y=0)
        self._embed.bind("<Button-1>",        self._on_left)
        self._embed.bind("<Button-3>",        self._on_right_press)
        self._embed.bind("<ButtonRelease-3>", self._on_right_release)
        self._embed.bind("<B3-Motion>",       self._on_right_drag)

        self.eval_canvas = tk.Canvas(self, width=EVAL_W, height=BOARD_SZ,
                                     bg="#1A1A1A", highlightthickness=0)
        self.eval_canvas.place(x=BOARD_SZ+4, y=0)

        self._rclick_start = None   # (row, col, px, py) of right-press

    def draw_eval_bar(self, score, mate=None, result=None):
        """
        Vertical eval bar. Mate-in-X shown prominently in colour:
          white mates -> green label
          black mates -> red label
        """
        c = self.eval_canvas; h = BOARD_SZ
        c.delete("all")
        sc = max(-2000, min(2000, score))
        split = int(h * (0.5 - sc/4000.0))
        c.create_rectangle(0, 0, EVAL_W, split, fill="#1C1C1C", outline="")
        c.create_rectangle(0, split, EVAL_W, h,  fill="#C8C8C8", outline="")
        if result:
            etxt = result; ecol = "#A0A080"
        elif mate is not None:
            etxt = f"M{abs(mate)}"; ecol = "#80FF88" if mate > 0 else "#FF8888"
        else:
            val = score/100.0; etxt = f"+{val:.1f}" if val > 0 else f"{val:.1f}"; ecol = "#777777"
        c.create_text(EVAL_W//2, h//2, text=etxt, anchor="center",
                      fill=ecol, font=_font(8, bold=True), angle=90)
        print(f"[DEBUG eval_bar] score={score} mate={mate} label={etxt}")

    def _on_left(self, event):
        print(f"[DEBUG board] left-click ({event.x},{event.y})")
        erased = self.game.annot_erase(event.x, event.y)
        if not erased:
            if self.game.promo_move: self.game._promo_click(event.x, event.y)
            else:                    self.game._board_click(event.x, event.y)

    def _on_right_press(self, event):
        row, col = self.game._px_cell(event.x, event.y)
        if self.game.board.in_bounds(row, col):
            self._rclick_start = (row, col, event.x, event.y)
            print(f"[DEBUG annot] right-press ({row},{col})")

    def _on_right_drag(self, event):
        if self._rclick_start:
            _, _, x0, y0 = self._rclick_start
            self.game.annot_drag_preview = (x0, y0, event.x, event.y)

    def _on_right_release(self, event):
        self.game.annot_drag_preview = None
        if self._rclick_start is None: return
        r0, c0, x0, y0 = self._rclick_start
        self._rclick_start = None
        row, col = self.game._px_cell(event.x, event.y)
        if not self.game.board.in_bounds(row, col): return
        if (row, col) == (r0, c0):
            self.game.annot_toggle_highlight(row, col)
        else:
            self.game.annot_toggle_arrow((r0, c0), (row, col))
        print(f"[DEBUG annot] released ({row},{col})")

    def get_embed_id(self):
        self._embed.update(); return self._embed.winfo_id()


# ─────────────────────────────────────────────────────────────────────────────
# Main game class
# ─────────────────────────────────────────────────────────────────────────────
class FairyChess:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Fairy Chess")
        self.root.configure(bg=TK_BG)
        self.root.resizable(False, False)
        ChessPanel.apply_theme(self.root)
        self.flipped = False

        # Annotations
        self.annot_highlights   = {}   # {(row,col): color_idx}
        self.annot_arrows       = {}   # {((r0,c0),(r1,c1)): color_idx}
        self.annot_drag_preview = None # (x0,y0,x1,y1) or None

        self.board_canvas = BoardCanvas(self.root, self)
        self.board_canvas.pack(side="left", fill="both")
        self.panel = ChessPanel(self.root, self)
        self.panel.pack(side="left", fill="both")

        embed_id = self.board_canvas.get_embed_id()
        os.environ["SDL_WINDOWID"] = str(embed_id)
        if sys.platform == "win32": os.environ["SDL_VIDEODRIVER"] = "windib"
        elif sys.platform.startswith("linux"): os.environ["SDL_VIDEODRIVER"] = "x11"

        pygame.init()
        self._coord_font = None
        self.pg_surf = pygame.display.set_mode((BOARD_SZ, BOARD_SZ))
        self.clock   = pygame.time.Clock()

        self.imgs        = load_images(CELL - 10)
        self.tk_icons    = load_tk_icons(52)
        self.tk_icons_sm = load_tk_icons(MaterialTray.ICON)
        self.panel.material.set_icons(self.tk_icons_sm)

        self.piece_types = build_default_pieces()
        self.gen         = MoveGenerator()
        self._init_game_state()

        self.root.bind("<KeyPress-n>", lambda e: self.new_game())
        self.root.bind("<KeyPress-u>", lambda e: self.undo())
        self.root.bind("<KeyPress-e>", lambda e: self.open_editor())
        self.root.bind("<KeyPress-a>", lambda e: self.trigger_ai())
        self.root.bind("<KeyPress-f>", lambda e: self.flip_board())
        self.root.bind("<KeyPress-b>", lambda e: self.open_board_edit())
        self.root.bind("<KeyPress-p>", lambda e: self.open_packs())
        self.root.bind("<Left>",  lambda e: self.go_prev())
        self.root.bind("<Right>", lambda e: self.go_next())
        self.root.bind("<Home>",  lambda e: self.go_to(0))
        self.root.bind("<End>",   lambda e: self.go_last())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._prev_time = time.time(); self._running = True
        self.root.after(16, self._pg_tick)
        print("[DEBUG gui] FairyChess v4 ready")

    def _init_game_state(self, custom_board=None):
        if custom_board is not None:
            self.board = custom_board
        else:
            self.board = Board(8, 8); pt = self.piece_types
            order = ["Rook","Knight","Bishop","Queen","King","Bishop","Knight","Rook"]
            for c, name in enumerate(order):
                if name in pt:
                    self.board.place(Piece(pt[name], 0, 0, c))
                    self.board.place(Piece(pt[name], 1, 7, c))
            for c in range(8):
                if "Pawn" in pt:
                    self.board.place(Piece(pt["Pawn"], 0, 1, c))
                    self.board.place(Piece(pt["Pawn"], 1, 6, c))

        self.game_over = False; self.game_over_msg = ""; self.result_badge = ""
        self.selected = None; self.legal_moves = []; self.last_move = None
        self.promo_move = None; self.promo_opts = []
        self.anim_move = None; self.anim_fades = []; self.anim_shake = None
        self.anim_mate = None; self.anim_draw = None; self.anim_queue = []
        self.board_hist = [self.board.clone()]
        self.move_rec = []; self.san_rec = []
        self.nav_cur = 0; self.navigating = False
        self.ai_thinking = False; self.ai_thread = None
        self.eval_score = 0; self.last_ai_t = 0; self._checked_kings = []
        self.annot_highlights = {}; self.annot_arrows = {}; self.annot_drag_preview = None
        self._update_panel()
        print("[DEBUG gui] game state initialised")

    # ── Annotation helpers ────────────────────────────────────────────────────
    def annot_toggle_highlight(self, row, col):
        """Right-click same square: cycle colours 0-3, then remove."""
        key = (row, col); cur = self.annot_highlights.get(key, -1); nxt = cur + 1
        if nxt >= len(ANNOT_COLORS): del self.annot_highlights[key]
        else:                        self.annot_highlights[key] = nxt
        print(f"[DEBUG annot] highlight ({row},{col}) -> {nxt}")

    def annot_toggle_arrow(self, from_sq, to_sq):
        """Right-drag: add arrow, or remove if already present."""
        key = (from_sq, to_sq)
        if key in self.annot_arrows: del self.annot_arrows[key]
        else:                        self.annot_arrows[key] = 0
        print(f"[DEBUG annot] arrow {key} toggled")

    def annot_erase(self, x, y):
        """Left-click: erase highlight/arrow at this square. Returns True if erased."""
        row, col = self._px_cell(x, y); erased = False
        if (row, col) in self.annot_highlights:
            del self.annot_highlights[(row, col)]; erased = True
        to_del = [k for k in self.annot_arrows if k[0]==(row,col) or k[1]==(row,col)]
        for k in to_del: del self.annot_arrows[k]; erased = True
        if erased: print(f"[DEBUG annot] erased at ({row},{col})")
        return erased

    def annot_clear(self):
        self.annot_highlights.clear(); self.annot_arrows.clear()
        self.annot_drag_preview = None
        print("[DEBUG annot] cleared")

    # ── Coordinate helpers ────────────────────────────────────────────────────
    def _cell_px(self, row, col):
        if self.flipped: return (7-col)*CELL, row*CELL
        return col*CELL, (7-row)*CELL

    def _px_cell(self, x, y):
        if self.flipped: return y//CELL, 7-x//CELL
        return (7-y//CELL), x//CELL

    def _cell_center(self, row, col):
        x, y = self._cell_px(row, col); return x+CELL//2, y+CELL//2

    # ── Mode helpers ──────────────────────────────────────────────────────────
    def _mode(self):    return self.panel.get_mode()
    def _elo_idx(self): return self.panel.get_elo_idx()
    def _human_turn(self):
        m = self._mode(); cp = self.board.current_player
        if m == "Human vs Human": return True
        if m == "Human vs AI":    return cp == 0
        return False

    def on_mode_change(self):   self.new_game()
    def on_accent_change(self): pass

    def new_game(self):
        print("[DEBUG gui] new game"); self._init_game_state()

    def flip_board(self):
        self.flipped = not self.flipped
        print(f"[DEBUG gui] board flipped={self.flipped}")

    def open_board_edit(self):
        BoardEditWindow(self.root, board=self.board, piece_types=self.piece_types,
                        tk_icons=self.tk_icons, accent=self.panel.get_accent_hex(),
                        on_apply=self._on_board_edit_apply)

    def _on_board_edit_apply(self, new_board):
        self._init_game_state(custom_board=new_board)
        self._check_over(); self._async_eval()
        print("[DEBUG gui] board edit applied")

    def open_packs(self):
        PackManagerWindow(self.root, on_pack_reload=self._reload_images)

    def _reload_images(self):
        self.imgs = load_images(CELL-10); self.tk_icons = load_tk_icons(52)
        self.tk_icons_sm = load_tk_icons(MaterialTray.ICON)
        self.panel.material.set_icons(self.tk_icons_sm); self.panel.material.refresh(self.board)
        print("[DEBUG gui] images reloaded")

    def open_editor(self):
        from piece_editor import EditorWindow
        EditorWindow(self.root, self.piece_types, self.imgs, self.panel.get_accent_hex(), self._on_editor_save)

    def _on_editor_save(self, new_piece_types):
        self.piece_types = new_piece_types
        self.imgs = load_images(CELL-10); self.tk_icons = load_tk_icons(52)
        self.tk_icons_sm = load_tk_icons(MaterialTray.ICON)
        self.panel.material.set_icons(self.tk_icons_sm)
        print(f"[DEBUG gui] editor saved {len(self.piece_types)} types")

    def undo(self):
        if len(self.board_hist) < 2 or self.ai_thinking: return
        self.board_hist.pop()
        if self.move_rec: self.move_rec.pop()
        if self.san_rec:  self.san_rec.pop()
        self.board = self.board_hist[-1].clone(); self.nav_cur = len(self.board_hist)-1
        self.navigating = False; self.game_over = False; self.result_badge = ""
        self.promo_move = None; self.selected = None; self.legal_moves = []
        self.last_move = self.move_rec[-1] if self.move_rec else None
        self.annot_clear(); self._check_over(); self._async_eval(); self._update_panel()
        print("[DEBUG gui] undo")

    def go_to(self, idx):
        idx = max(0, min(len(self.board_hist)-1, idx))
        self.nav_cur = idx; self.board = self.board_hist[idx].clone()
        self.navigating = (idx < len(self.board_hist)-1); self.selected = None; self.legal_moves = []
        self.last_move = self.move_rec[idx-1] if idx > 0 else None
        self.anim_move = None; self.anim_fades = []
        self._check_over(); self._update_panel()

    def go_prev(self): self.go_to(self.nav_cur-1)
    def go_next(self): self.go_to(self.nav_cur+1)
    def go_last(self): self.go_to(len(self.board_hist)-1)

    def trigger_ai(self):
        if self.ai_thinking or self.game_over or self.anim_move or self.promo_move: return
        if self.navigating: self.go_last(); return
        self.ai_thinking = True; self.panel.set_status("AI thinking...", TK_DIM)
        snap = self.board; owner = snap.current_player; idx = self._elo_idx()
        def worker():
            mv = get_best_move(snap, owner, elo_idx=idx)
            self.ai_thinking = False
            if mv: self.anim_queue.append(mv)
            else:
                self.root.after(0, lambda: self.panel.set_status("AI has no moves", TK_DIM))
                self._check_over()
            print(f"[DEBUG gui] AI done, queued: {mv}")
        self.ai_thread = threading.Thread(target=worker, daemon=True)
        self.ai_thread.start()

    def _san(self, move, board_before):
        fr, fc = move["from_pos"]; tr, tc = move["to_pos"]
        p = board_before.get(fr, fc)
        if not p: return "?"
        sym = p.piece_type.symbol
        if move.get("castling"): return "O-O" if tc > fc else "O-O-O"
        cap = "x" if move.get("captured_uid") else "-"
        ep = " e.p." if move.get("en_passant_capture") else ""
        promo = f"={move.get('promotion','')}" if move.get("promotion") else ""
        f = "abcdefgh"
        return f"{''+sym if sym not in ('P','p') else ''}{f[fc]}{fr+1}{cap}{f[tc]}{tr+1}{promo}{ep}"

    def _apply(self, move, animate=True):
        if self.navigating: self.go_last()
        fr, fc = move["from_pos"]; tr, tc = move["to_pos"]
        piece = self.board.get(fr, fc)
        if not piece: return
        self.annot_clear()
        if move.get("captured_uid"):
            cap_pos = move.get("en_passant_capture") or (tr, tc)
            for p in self.board.all_pieces():
                if p.uid == move["captured_uid"]:
                    cpx, cpy = self._cell_px(*cap_pos)
                    self.anim_fades.append(FadePiece(p, cpx, cpy)); break
        if move.get("needs_promotion") and not move.get("promotion_type"):
            auto = ("AI" in self._mode() and self.board.current_player != 0) or self._mode() == "AI vs AI"
            if auto:
                move = dict(move); move["promotion"] = "Queen"; move["promotion_type"] = self.piece_types.get("Queen")
            else:
                self.promo_move = move; self.promo_opts = move.get("promotion_options", ["Queen","Rook","Bishop","Knight"])
                if animate: self.anim_move = MovingPiece(piece, self._cell_px(fr,fc), self._cell_px(tr,tc))
                return
        if animate: self.anim_move = MovingPiece(piece, self._cell_px(fr,fc), self._cell_px(tr,tc))
        san = self._san(move, self.board)
        self.board = self.board.apply_move(move)
        self.board_hist.append(self.board.clone()); self.move_rec.append(move); self.san_rec.append(san)
        self.nav_cur = len(self.board_hist)-1; self.last_move = move; self.selected = None; self.legal_moves = []
        self._check_over(); self._async_eval(); self._update_panel()

    def _check_over(self):
        result = self.gen.game_result(self.board)
        if result:
            self.game_over = True; cp = self.board.current_player
            winner = "Black" if cp == 0 else "White"
            msgs = {"checkmate": f"Checkmate — {winner} wins", "stalemate": "Stalemate — Draw",
                    "50move": "Draw — 50-move rule", "repetition": "Draw — Threefold repetition",
                    "material": "Draw — Insufficient material"}
            self.game_over_msg = msgs.get(result, "Game over")
            col = TK_GOLD if "wins" in self.game_over_msg else TK_DIM
            self.root.after(0, lambda: self.panel.set_status(self.game_over_msg, col))
            if result == "checkmate":
                self.result_badge = "0-1" if cp == 0 else "1-0"
                king = self.board.find_king(cp)
                if king: self.anim_mate = MatePulse(king.row, king.col)
            else:
                self.result_badge = "1/2"; self.anim_draw = DrawFlash()
            self.root.after(0, lambda rb=self.result_badge: (
                self.panel.set_eval(self.eval_score, result=rb),
                self.board_canvas.draw_eval_bar(self.eval_score, result=rb)))
        else:
            self.result_badge = ""; cp = self.board.current_player
            in_chk = self.gen.is_in_check(self.board, cp)
            name = "White" if cp == 0 else "Black"
            txt = f"{name} in CHECK" if in_chk else f"{name} to move"
            col = TK_RED if in_chk else TK_TXT
            self.root.after(0, lambda t=txt, c=col: self.panel.set_status(t, c))
        self._checked_kings = []
        for owner in [0,1]:
            if self.gen.is_in_check(self.board, owner):
                king = self.board.find_king(owner)
                if king: self._checked_kings.append((king.row, king.col))
        print(f"[DEBUG gui] result={result} badge={self.result_badge} checked={self._checked_kings}")

    def _update_panel(self):
        def _do():
            self.panel.update_movelist(self.san_rec, self.nav_cur, self.result_badge)
            self.panel.material.refresh(self.board)
        self.root.after(0, _do)

    def _async_eval(self):
        """Background evaluation with Mate-in-X detection."""
        snap = self.board
        def worker():
            score = quick_eval(snap, 0); mate = None
            if score >= 90000:
                dist = (100000-score)//100 + 1; mate = dist
            elif score <= -90000:
                dist = (100000+score)//100 + 1; mate = -dist
            self.eval_score = score
            self.root.after(0, lambda s=score, m=mate: (
                self.panel.set_eval(s, mate=m), self.board_canvas.draw_eval_bar(s, mate=m)))
        threading.Thread(target=worker, daemon=True).start()

    def _board_click(self, x, y):
        if self.game_over or self.anim_move or self.ai_thinking or self.promo_move: return
        if x >= BOARD_SZ: return
        row, col = self._px_cell(x, y)
        if not self.board.in_bounds(row, col): return
        if self.navigating: self.go_last(); return
        if not self._human_turn(): return
        clicked = self.board.get(row, col)
        if self.selected:
            mv = next((m for m in self.legal_moves if m["to_pos"]==(row,col)), None)
            if mv:
                self._apply(mv); mode = self._mode()
                if not self.game_over and mode == "Human vs AI": self.root.after(350, self.trigger_ai)
                elif mode == "Human vs Human" and not self.game_over: self.root.after(300, self.flip_board)
                return
            self.selected = None; self.legal_moves = []
            if clicked and clicked.owner == self.board.current_player: pass
            else: self.anim_shake = ShakeAnim(row, col); return
        if clicked and clicked.owner == self.board.current_player:
            self.selected = clicked; self.legal_moves = self.gen.get_moves(clicked, self.board, legal_only=True)
        else: self.anim_shake = ShakeAnim(row, col)

    def _promo_click(self, x, y):
        if not self.promo_move: return
        n = len(self.promo_opts); bw, bh = 82, 96
        bx = BOARD_SZ//2 - n*bw//2; by = BOARD_SZ//2 - bh//2
        for i, name in enumerate(self.promo_opts):
            r = pygame.Rect(bx+i*bw, by, bw-4, bh)
            if r.collidepoint(x, y):
                mv = dict(self.promo_move); mv["promotion"] = name
                mv["promotion_type"] = self.piece_types.get(name)
                self.promo_move = None; bb = self.board
                self.board = self.board.apply_move(mv)
                self.board_hist.append(self.board.clone()); self.move_rec.append(mv)
                self.san_rec.append(self._san(mv, bb))
                self.nav_cur = len(self.board_hist)-1; self.last_move = mv; self.selected = None
                self._check_over(); self._async_eval(); self._update_panel()
                if not self.game_over and self._mode() == "Human vs AI": self.root.after(350, self.trigger_ai)
                return

    def _pg_tick(self):
        if not self._running: return
        now = time.time(); dt = min(now-self._prev_time, 0.05); self._prev_time = now
        for ev in pygame.event.get():
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.promo_move: self._promo_click(*ev.pos)
                else:               self._board_click(*ev.pos)
        self._update_anims(dt)
        if (self._mode()=="AI vs AI" and not self.game_over and not self.ai_thinking and
                not self.anim_move and not self.promo_move and not self.anim_queue and not self.navigating):
            if now - self.last_ai_t > 0.5: self.last_ai_t = now; self.trigger_ai()
        if self.anim_queue and not self.anim_move and not self.promo_move:
            self._apply(self.anim_queue.pop(0))
        self._draw()
        pygame.display.flip(); self.clock.tick(FPS); self.root.after(1, self._pg_tick)

    def _update_anims(self, dt):
        if self.anim_move:
            self.anim_move.update(dt)
            if self.anim_move.done: self.anim_move = None
        self.anim_fades = [f for f in self.anim_fades if not f.done]
        for f in self.anim_fades: f.update(dt)
        if self.anim_shake:
            self.anim_shake.update(dt)
            if self.anim_shake.done: self.anim_shake = None
        if self.anim_mate:  self.anim_mate.update(dt)
        if self.anim_draw:
            self.anim_draw.update(dt)
            if self.anim_draw.done: self.anim_draw = None

    def _draw(self):
        acc = self.panel.get_accent_rgb()
        self.pg_surf.fill(BG_COL)
        self._draw_board(self.pg_surf, acc)
        self._draw_annotations(self.pg_surf)
        self._draw_pieces(self.pg_surf)
        self._draw_promo(self.pg_surf, acc)
        self._draw_gameover(self.pg_surf, acc)

    def _draw_board(self, surf, accent_rgb):
        if not self._coord_font:
            try:    self._coord_font = pygame.font.SysFont("DejaVu Sans", 13, bold=True)
            except: self._coord_font = pygame.font.Font(None, 16)
        font = self._coord_font
        for row in range(8):
            for col in range(8):
                x, y = self._cell_px(row, col); ox = 0
                if self.anim_shake and self.anim_shake.row==row and self.anim_shake.col==col:
                    ox = self.anim_shake.offset
                light = (row+col)%2 == 0; sq_col = SQ_LIGHT if light else SQ_DARK
                pygame.draw.rect(surf, sq_col, (x+ox, y, CELL, CELL))
                if self.last_move and (row,col) in [self.last_move["from_pos"],self.last_move["to_pos"]]:
                    hl = pygame.Surface((CELL,CELL),pygame.SRCALPHA); hl.fill(LM_COL); surf.blit(hl,(x,y))
                if self.anim_mate and self.anim_mate.row==row and self.anim_mate.col==col:
                    hl = pygame.Surface((CELL,CELL),pygame.SRCALPHA); hl.fill((*CHK_COL[:3],self.anim_mate.alpha)); surf.blit(hl,(x,y))
                if self.anim_draw:
                    hl = pygame.Surface((CELL,CELL),pygame.SRCALPHA); hl.fill((205,165,55,self.anim_draw.alpha)); surf.blit(hl,(x,y))
                for kp in self._checked_kings:
                    if kp == (row,col):
                        hl = pygame.Surface((CELL,CELL),pygame.SRCALPHA); hl.fill(CHK_COL); surf.blit(hl,(x,y))
                if self.selected and self.selected.row==row and self.selected.col==col:
                    hl = pygame.Surface((CELL,CELL),pygame.SRCALPHA); hl.fill(SEL_COL); surf.blit(hl,(x,y))
                for mv in self.legal_moves:
                    if mv["to_pos"]==(row,col):
                        if mv.get("captured_uid"):
                            pygame.draw.circle(surf, CAP_COL, (x+CELL//2,y+CELL//2), CELL//2-3, 4)
                        else:
                            pygame.draw.circle(surf, DOT_COL, (x+CELL//2,y+CELL//2), CELL//8)
        # Coordinates
        for i in range(8):
            br = i if self.flipped else (7-i); nc = COORD_ON_LIGHT if (br+0)%2==0 else COORD_ON_DARK
            rs = font.render(str(br+1), True, nc); surf.blit(rs, (2, i*CELL+3))
            bc = (7-i) if self.flipped else i; fl = "abcdefgh"[bc]
            lc = COORD_ON_LIGHT if (0+bc)%2==0 else COORD_ON_DARK
            ls = font.render(fl, True, lc); surf.blit(ls, (i*CELL+CELL-ls.get_width()-3, BOARD_SZ-ls.get_height()-3))
        if self.navigating:
            ov = pygame.Surface((BOARD_SZ,28),pygame.SRCALPHA); ov.fill((0,0,0,195)); surf.blit(ov,(0,0))
            msg = f"Move {self.nav_cur}/{len(self.board_hist)-1}  —  click board to resume"
            s = font.render(msg, True, accent_rgb); surf.blit(s, (BOARD_SZ//2-s.get_width()//2, 6))

    def _draw_annotations(self, surf):
        """Highlights and arrows — drawn between board squares and pieces."""
        for (row, col), cidx in self.annot_highlights.items():
            x, y = self._cell_px(row, col)
            hl = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
            hl.fill(ANNOT_COLORS[cidx % len(ANNOT_COLORS)])
            surf.blit(hl, (x, y))
        for (from_sq, to_sq), cidx in self.annot_arrows.items():
            cx1, cy1 = self._cell_center(*from_sq)
            cx2, cy2 = self._cell_center(*to_sq)
            draw_arrow(surf, cx1, cy1, cx2, cy2, ANNOT_COLORS[cidx % len(ANNOT_COLORS)])
        if self.annot_drag_preview:
            x0, y0, x1, y1 = self.annot_drag_preview
            draw_arrow(surf, x0, y0, x1, y1, (255, 255, 255, 110))

    def _draw_pieces(self, surf):
        auid = self.anim_move.piece.uid if self.anim_move else None
        for fa in self.anim_fades: draw_piece(surf, self.imgs, fa.piece, fa.px, fa.py, alpha=fa.alpha, scale=fa.scale)
        for row in range(8):
            for col in range(8):
                p = self.board.get(row, col)
                if p and p.uid != auid:
                    px, py = self._cell_px(row, col); draw_piece(surf, self.imgs, p, px, py)
        if self.anim_move:
            ax, ay = self.anim_move.pos; draw_piece(surf, self.imgs, self.anim_move.piece, int(ax), int(ay))

    def _draw_promo(self, surf, accent_rgb):
        if not self.promo_move: return
        n = len(self.promo_opts); bw, bh = 82, 96
        bx = BOARD_SZ//2 - n*bw//2; by = BOARD_SZ//2 - bh//2
        ov = pygame.Surface((BOARD_SZ,BOARD_SZ),pygame.SRCALPHA); ov.fill((0,0,0,155)); surf.blit(ov,(0,0))
        box = pygame.Rect(bx-18, by-44, n*bw+36, bh+64)
        pygame.draw.rect(surf, (18,18,28), box, border_radius=14)
        pygame.draw.rect(surf, accent_rgb, box, 2, border_radius=14)
        try: fn = pygame.font.SysFont("DejaVu Sans",13)
        except: fn = pygame.font.Font(None,16)
        title = fn.render("Promote to:", True, accent_rgb)
        surf.blit(title, (box.centerx-title.get_width()//2, box.y+10))
        owner = self.board.current_player ^ 1
        for i, name in enumerate(self.promo_opts):
            r = pygame.Rect(bx+i*bw, by, bw-4, bh)
            pygame.draw.rect(surf, (32,32,48), r, border_radius=8)
            pygame.draw.rect(surf, accent_rgb, r, 1, border_radius=8)
            if name in self.piece_types:
                dummy = Piece(self.piece_types[name], owner, 0, 0)
                draw_piece(surf, self.imgs, dummy, r.x, r.y, size=bw-4, scale=0.82)
            lbl = fn.render(name, True, (200,200,216))
            surf.blit(lbl, (r.centerx-lbl.get_width()//2, r.bottom-16))

    def _draw_gameover(self, surf, accent_rgb):
        if not self.game_over: return
        ov = pygame.Surface((BOARD_SZ,BOARD_SZ),pygame.SRCALPHA); ov.fill((0,0,0,125)); surf.blit(ov,(0,0))
        box = pygame.Rect(BOARD_SZ//2-230, BOARD_SZ//2-54, 460, 108)
        pygame.draw.rect(surf, (14,14,22), box, border_radius=14)
        pygame.draw.rect(surf, accent_rgb, box, 2, border_radius=14)
        try: fL = pygame.font.SysFont("DejaVu Sans",20,bold=True); fS = pygame.font.SysFont("DejaVu Sans",12)
        except: fL = pygame.font.Font(None,26); fS = pygame.font.Font(None,16)
        badge = f"  [{self.result_badge}]" if self.result_badge else ""
        lbl = fL.render(self.game_over_msg+badge, True, accent_rgb)
        surf.blit(lbl, (box.centerx-lbl.get_width()//2, box.y+14))
        sub = fS.render("N  new game       U  undo       F  flip board", True, (90,90,112))
        surf.blit(sub, (box.centerx-sub.get_width()//2, box.y+60))

    def _on_close(self):
        self._running = False; pygame.quit(); self.root.destroy()

    def run(self):
        self.root.mainloop(); print("[DEBUG gui] quit")


if __name__ == "__main__":
    FairyChess().run()

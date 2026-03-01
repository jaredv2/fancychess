"""
gui.py — Fancy Chess  v5  (production)
========================================
Architecture:
  Tkinter  : outer window + all UI controls
  Pygame   : board rendering embedded via SDL_WINDOWID

Features:
  - Name: "Fancy Chess"
  - Correct board coordinates: a-h left→right on bottom, 1-8 bottom→top on left
  - Sound system: move / capture / check / castle / promotion / checkmate (synthesised)
  - Checkmate animation: gold pulse + particle burst on king square
  - Mate-in-N: background thread computes forced mate depth, shown in eval bar
  - FEN load/export via panel buttons
  - Production-ready: structured logging, robust error handling, no debug prints
"""

import sys, os, math, time, threading, json, shutil, logging

sys.path.insert(0, os.path.dirname(__file__))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# ── Optional pygame ────────────────────────────────────────────────────────────
try:
    import pygame
    _PYGAME_OK = True
except ImportError:
    _PYGAME_OK = False

from logic import Board, Piece, MoveGenerator, build_default_pieces

# parse_fen / to_fen were added in a later revision of logic.py.
# Import them if available; otherwise provide lightweight fallback stubs
# so the rest of the UI still works (FEN buttons will show a friendly error).
try:
    from logic import parse_fen, to_fen
    _FEN_SUPPORTED = True
    print("[INFO gui] FEN support: available (parse_fen / to_fen loaded from logic)")
except ImportError:
    _FEN_SUPPORTED = False
    print("[WARN gui] FEN support: logic.py does not export parse_fen / to_fen — FEN buttons disabled")
    def parse_fen(fen: str, piece_types: dict) -> Board:           # type: ignore[misc]
        raise NotImplementedError(
            "parse_fen is not available in your logic.py.\n"
            "Please update logic.py to include the parse_fen() function.")
    def to_fen(board: Board) -> str:                               # type: ignore[misc]
        raise NotImplementedError(
            "to_fen is not available in your logic.py.\n"
            "Please update logic.py to include the to_fen() function.")

from ai    import get_best_move, quick_eval, ELO_LEVELS, find_mate_in_n

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fancy_chess")

print("[INFO gui] Fancy Chess v6 starting up")

# ─────────────────────────────────────────────────────────────────────────────
# Layout constants
# ─────────────────────────────────────────────────────────────────────────────
CELL     = 80
COORD_M  = 22          # margin: rank labels on left, file labels on bottom
BOARD_PX = 8 * CELL    # 640px — pure board without margin
EVAL_W   = 22
PANEL_W  = 370
FPS      = 60

# ─────────────────────────────────────────────────────────────────────────────
# Colours
# ─────────────────────────────────────────────────────────────────────────────
SQ_LIGHT       = (235, 236, 208)
SQ_DARK        = ( 86, 125,  70)
SEL_COL        = (246, 246, 105, 160)
DOT_COL        = ( 20,  85,  30, 200)
CAP_COL        = (204,  34,  34)
LM_COL         = (246, 246, 105,  90)
CHK_COL        = (220,  36,  36, 160)
BG_COL         = ( 18,  18,  26)
COORD_LIGHT    = ( 86, 125,  70)
COORD_DARK     = (235, 236, 208)

# ─────────────────────────────────────────────────────────────────────────────
# Cached overlay surfaces — created ONCE after pygame.init(), reused every frame.
# Eliminates the biggest GC/alloc hotspot in _draw_board (was ~200 Surface()
# calls per frame at 60 fps = 12 000 allocations/second).
# ─────────────────────────────────────────────────────────────────────────────
_OV: dict = {}   # populated by _init_overlays() after pygame starts

def _init_overlays():
    """Pre-bake every per-cell overlay surface. Call once after pygame.init()."""
    global _OV
    if _OV:
        return   # already initialised
    def _surf(color):
        s = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        s.fill(color)
        return s
    _OV["lm"]  = _surf(LM_COL)
    _OV["sel"] = _surf(SEL_COL)
    _OV["chk"] = _surf(CHK_COL)
    _OV["draw_flash"] = _surf((205, 165, 55, 90))   # base; alpha set at draw time
    _OV["annot0"] = _surf((255, 165,  30, 180))
    _OV["annot1"] = _surf((220,  50,  50, 180))
    _OV["annot2"] = _surf(( 50, 120, 220, 180))
    _OV["annot3"] = _surf(( 50, 200,  90, 180))
    _OV["nav"]    = pygame.Surface((BOARD_PX, 28), pygame.SRCALPHA)
    _OV["nav"].fill((0, 0, 0, 195))
    _OV["arrow_tmp"] = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
    print(f"[INFO gui] Overlay cache initialised ({len(_OV)} surfaces)")

ANNOT_COLORS = [
    (255, 165,  30, 180),
    (220,  50,  50, 180),
    ( 50, 120, 220, 180),
    ( 50, 200,  90, 180),
]
ARROW_BODY_W  = 10
ARROW_HEAD_SZ = 18

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

SYM_FILE = {"K": "king", "Q": "queen", "R": "rook",
            "B": "bishop", "N": "knight", "P": "pawn"}
PIECE_CP = {"Q": 900, "R": 500, "B": 330, "N": 320, "P": 100, "K": 0}


def _font(size=10, bold=False, mono=False):
    if mono: return ("DejaVu Sans Mono", size)
    return ("Poppins", size, "bold") if bold else ("Poppins", size)


# ─────────────────────────────────────────────────────────────────────────────
# Asset loading
# ─────────────────────────────────────────────────────────────────────────────
_PACKS_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs.json")


def _load_packs_cfg():
    if os.path.isfile(_PACKS_CFG):
        try:
            with open(_PACKS_CFG) as f: return json.load(f)
        except Exception as e:
            log.warning("packs.json read error: %s", e)
    return {}


def _save_packs_cfg(cfg):
    try:
        with open(_PACKS_CFG, "w") as f: json.dump(cfg, f, indent=2)
    except Exception as e:
        log.error("packs.json write error: %s", e)


def _default_pack_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for base in [here, os.getcwd(), os.path.join(here, "..")]:
        p = os.path.join(base, "assets", "chessmat")
        if os.path.isdir(p): return p
    return None


def _get_active_root():
    cfg = _load_packs_cfg(); active = cfg.get("__active__", "")
    if active and active in cfg:
        path = cfg[active]
        if os.path.isdir(path): return path
    return _default_pack_root()


def load_images(size, pack_root=None):
    """
    Load pygame surfaces for all pieces.

    `size` is the cell size. Images are pre-scaled to the exact draw size
    (cell minus margins) so draw_piece can blit directly without any
    per-frame transform — the most important single performance fix.
    """
    if not _PYGAME_OK: return {}
    margin  = max(4, int(size * 0.07))
    draw_sz = max(4, size - margin * 2)   # matches draw_piece calculation
    imgs = {}; root = pack_root or _get_active_root()
    if not root: return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path): continue
            try:
                raw = pygame.image.load(path).convert_alpha()
                imgs[(sym, owner)] = pygame.transform.smoothscale(raw, (draw_sz, draw_sz))
            except Exception as e:
                log.warning("Image load error %s: %s", path, e)
    print(f"[INFO gui] Loaded {len(imgs)}/12 piece images @ {draw_sz}px (cell={size})")
    return imgs


def load_tk_icons(size=32, pack_root=None):
    """Load Tkinter PhotoImages for all pieces (used in panel/setup)."""
    imgs = {}; root = pack_root or _get_active_root()
    if not root: return imgs
    try:
        from PIL import Image as PilImg, ImageTk as PilTk
    except ImportError:
        return imgs
    for owner, folder in [(0, "white"), (1, "black")]:
        for sym, fname in SYM_FILE.items():
            path = os.path.join(root, folder, f"{fname}.png")
            if not os.path.isfile(path): continue
            try:
                img = PilImg.open(path).convert("RGBA").resize((size, size), PilImg.LANCZOS)
                imgs[(sym, owner)] = PilTk.PhotoImage(img)
            except Exception as e:
                log.warning("TK icon error %s: %s", path, e)
    return imgs


# ─────────────────────────────────────────────────────────────────────────────
# Sound system — all sounds are synthesised; no external files needed
# ─────────────────────────────────────────────────────────────────────────────
class SoundSystem:
    """
    Synthesised chess sounds via pygame.mixer + numpy.

    Sound design:
      move      - soft wooden thud (low sine + click transient)
      capture   - heavier crunch (low sine + noise burst)
      check     - two rising beeps (alert tone)
      castle    - double thud (two overlapping low tones)
      promotion - rising fanfare (four ascending notes)
      checkmate - dramatic descending sweep (glide + noise)

    Falls back silently if pygame.mixer or numpy is unavailable.
    """

    def __init__(self):
        self._ok = False
        self._sounds = {}
        if not _PYGAME_OK:
            print("[INFO gui] SoundSystem: pygame not available, sounds disabled")
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._sounds = {
                "move":      self._make_move(),
                "capture":   self._make_capture(),
                "check":     self._make_check(),
                "castle":    self._make_castle(),
                "promotion": self._make_promotion(),
                "checkmate": self._make_checkmate(),
            }
            self._ok = True
            print("[INFO gui] SoundSystem: all 6 sounds synthesised OK")
        except Exception as e:
            log.warning("Sound init error: %s", e)
            print(f"[WARN gui] SoundSystem init failed: {e}")

    # ── Synthesis helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _make_sound(samples_int16):
        """Wrap a numpy int16 array as a mono pygame Sound."""
        try:
            import numpy as np
            arr = samples_int16.reshape(-1, 1)
            return pygame.sndarray.make_sound(arr)
        except Exception as e:
            log.warning("Sound make error: %s", e)
            return None

    def _make_move(self):
        """Soft wooden thud: low sine decay + brief high-freq click."""
        try:
            import numpy as np
            sr = 44100; dur = 0.09
            t = np.linspace(0, dur, int(sr * dur), False)
            wave  = np.sin(2 * np.pi * 280 * t) * np.exp(-t * 40)
            click = np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 120) * 0.35
            sig = ((wave + click) * 28000).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("move sound error: %s", e); return None

    def _make_capture(self):
        """Heavier crunch: low sine + noise burst."""
        try:
            import numpy as np
            sr = 44100; dur = 0.13
            t = np.linspace(0, dur, int(sr * dur), False)
            wave   = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 28)
            crunch = np.random.uniform(-1, 1, len(t)) * np.exp(-t * 60) * 0.5
            sig = ((wave + crunch) * 26000).clip(-32768, 32767).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("capture sound error: %s", e); return None

    def _make_check(self):
        """Two rising beeps: 880 Hz → 1100 Hz."""
        try:
            import numpy as np
            sr = 44100; dur = 0.18
            t = np.linspace(0, dur, int(sr * dur), False)
            wave  = np.sin(2 * np.pi * 880  * t) * np.where(t < 0.09, 1, 0) * np.exp(-t * 15)
            wave += np.sin(2 * np.pi * 1100 * t) * np.where(t >= 0.09, 1, 0) * np.exp(-(t - 0.09) * 15)
            sig = (wave * 22000).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("check sound error: %s", e); return None

    def _make_castle(self):
        """Double thud: two overlapping 300/280 Hz tones."""
        try:
            import numpy as np
            sr = 44100; dur = 0.18
            t = np.linspace(0, dur, int(sr * dur), False)
            t2 = np.clip(t - 0.09, 0, None)
            wave = (np.sin(2 * np.pi * 300 * t)  * np.exp(-t  * 35) +
                    np.sin(2 * np.pi * 280 * t2) * np.exp(-t2 * 35) * 0.8)
            sig = (wave * 25000).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("castle sound error: %s", e); return None

    def _make_promotion(self):
        """Rising fanfare: four ascending notes 440→880 Hz."""
        try:
            import numpy as np
            sr = 44100; dur = 0.30
            t = np.linspace(0, dur, int(sr * dur), False)
            freqs = [440, 550, 660, 880]
            wave = np.zeros(len(t))
            for i, f in enumerate(freqs):
                ts = i * 0.07; te = ts + 0.12
                env = np.where((t >= ts) & (t < te), 1, 0) * np.exp(-np.clip(t - ts, 0, None) * 20)
                wave += np.sin(2 * np.pi * f * t) * env
            sig = (wave * 20000).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("promotion sound error: %s", e); return None

    def _make_checkmate(self):
        """Dramatic descending sweep: gliding frequency 880→220 Hz + noise fade."""
        try:
            import numpy as np
            sr = 44100; dur = 0.70
            t = np.linspace(0, dur, int(sr * dur), False)
            freq  = 880 - t * (880 - 220)
            wave  = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 4)
            noise = np.random.uniform(-1, 1, len(t)) * np.exp(-t * 8) * 0.15
            sig = ((wave + noise) * 24000).astype(np.int16)
            return self._make_sound(sig)
        except Exception as e:
            log.warning("checkmate sound error: %s", e); return None

    def play(self, name):
        """Play a named sound if available."""
        if not self._ok: return
        snd = self._sounds.get(name)
        if snd:
            try:
                snd.play()
                print(f"[INFO gui] Sound played: {name}")
            except Exception as e:
                log.warning("Sound play error %s: %s", name, e)


# ─────────────────────────────────────────────────────────────────────────────
# Drawing helpers
# ─────────────────────────────────────────────────────────────────────────────
def draw_piece(surf, imgs, piece, px, py, size=CELL, alpha=255, scale=1.0):
    """
    Draw a chess piece at pixel position (px,py) on a pygame surface.

    Performance: avoids smoothscale on every call by blitting the pre-scaled
    image directly for the common case (scale=1.0, alpha=255).
    Only re-scales when animating a captured piece (scale<1) or fading (alpha<255).
    """
    key = (piece.piece_type.symbol, piece.owner)
    img = imgs.get(key)
    margin = max(4, int(size * 0.07))
    draw_sz = max(4, int((size - margin * 2) * scale))
    cx = px + size // 2; cy = py + size // 2
    if img:
        if scale != 1.0 or img.get_width() != draw_sz:
            # Only re-scale when necessary (fade/capture animation)
            s = pygame.transform.smoothscale(img, (draw_sz, draw_sz))
        else:
            s = img
        if alpha < 255:
            s = s.copy(); s.set_alpha(alpha)
        surf.blit(s, (cx - draw_sz // 2, cy - draw_sz // 2))
    else:
        # Fallback: coloured circle when no image is available
        col = (230, 225, 218) if piece.owner == 0 else (52, 48, 44)
        pygame.draw.circle(surf, col, (cx, cy), draw_sz // 2)
        pygame.draw.circle(surf, (80, 80, 100), (cx, cy), draw_sz // 2, 2)


def draw_arrow(surf, x1, y1, x2, y2, color):
    """Draw a colored arrow from (x1,y1) to (x2,y2) on a pygame surface."""
    dx = x2 - x1; dy = y2 - y1; dist = math.hypot(dx, dy)
    if dist < 4: return
    nx = dx / dist; ny = dy / dist
    head_len = ARROW_HEAD_SZ
    sx2 = x2 - nx * head_len; sy2 = y2 - ny * head_len
    # Draw on an alpha surface then blit so the arrow can be translucent
    tmp = pygame.Surface((BOARD_PX, BOARD_PX + COORD_M), pygame.SRCALPHA)
    pygame.draw.line(tmp, color, (int(x1), int(y1)), (int(sx2), int(sy2)), ARROW_BODY_W)
    perp_x = -ny; perp_y = nx; hw = ARROW_HEAD_SZ * 0.55
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
    """Smooth piece slide animation using ease-out cubic."""
    SPEED = 28.0   # v7: crisp — completes in ~35ms (2 frames @60fps)

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
        # Ease-out cubic: decelerate as piece approaches target
        e = 1.0 - (1.0 - self.t) ** 3
        return (self.fx + (self.tx - self.fx) * e,
                self.fy + (self.ty - self.fy) * e)


class FadePiece:
    """Captured piece fade-out animation."""
    SPEED = 12.0   # v6: snappy fade

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
    """Horizontal shake on invalid-move click."""
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
    """Slow red pulse on the checked/mated king square."""
    def __init__(self, row, col): self.row = row; self.col = col; self.t = 0.0

    def update(self, dt): self.t += dt

    @property
    def alpha(self): return int(abs(math.sin(self.t * 3.0)) * 185)


class DrawFlash:
    """Whole-board golden flash on draw result."""
    def __init__(self, dur=1.2): self.t = 0.0; self.dur = dur; self.done = False

    def update(self, dt):
        self.t += dt
        if self.t >= self.dur: self.done = True

    @property
    def alpha(self):
        p = self.t / self.dur
        return int(math.sin(p * math.pi) * 60)


class CheckmateAnim:
    """
    Gold pulse + particle burst on the mated king's square.
    Particles radiate outward from the king centre with colour variation
    and fade over their individual lifespans.
    """
    def __init__(self, row, col):
        self.row = row; self.col = col
        self.t = 0.0; self.done = False; self.dur = 3.0
        import random
        # Each particle: [angle, speed, lifespan, color]
        self.particles = [
            [
                random.uniform(0, 2 * math.pi),
                random.uniform(40, 110),
                random.uniform(0.4, 1.0),
                random.choice([(255, 215, 0), (255, 140, 0), (255, 80, 80), (80, 220, 255)]),
            ]
            for _ in range(22)
        ]
        print(f"[INFO gui] CheckmateAnim started at ({row},{col})")

    def update(self, dt):
        self.t += dt
        if self.t >= self.dur: self.done = True

    def draw(self, surf, cx, cy):
        """Draw the animation centred on the king cell top-left at (cx,cy)."""
        if self.done: return
        p = self.t / self.dur

        # Pulsing gold background overlay
        alpha = int(abs(math.sin(self.t * 4)) * 200 * (1 - p * 0.5))
        hl = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        hl.fill((255, 215, 0, alpha))
        surf.blit(hl, (cx, cy))

        # Scatter particles
        for ang, spd, life, col in self.particles:
            age = self.t / life
            if age > 1.0: continue
            px2 = cx + CELL // 2 + math.cos(ang) * spd * self.t
            py2 = cy + CELL // 2 + math.sin(ang) * spd * self.t
            a = int((1 - age) * 220)
            if a < 5: continue
            r = max(2, int((1 - age) * 7))
            tmp = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(tmp, (*col, a), (r + 1, r + 1), r)
            surf.blit(tmp, (int(px2) - r, int(py2) - r))


# ─────────────────────────────────────────────────────────────────────────────
# Pack Manager window
# ─────────────────────────────────────────────────────────────────────────────
class PackManagerWindow(tk.Toplevel):
    def __init__(self, master, on_pack_reload=None):
        super().__init__(master)
        self.title("Piece Pack Manager — Fancy Chess")
        self.configure(bg=TK_BG); self.resizable(False, False); self.grab_set()
        self._on_pack_reload = on_pack_reload
        self._cfg = _load_packs_cfg()
        self._build()
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width() - self.winfo_width()) // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _build(self):
        BS = dict(bg=TK_SURF2, fg=TK_TXT, relief="flat", font=_font(10),
                  padx=8, pady=4, cursor="hand2",
                  activebackground=TK_SURF, activeforeground=TK_TXT, bd=0)
        F = tk.Frame(self, bg=TK_BG, padx=18, pady=16); F.pack(fill="both", expand=True)
        tk.Label(F, text="Piece Image Packs", bg=TK_BG, fg=TK_TXT,
                 font=_font(13, bold=True)).pack(anchor="w", pady=(0, 3))
        tk.Label(F, text="Pack folder must contain  white/  and  black/  subdirectories\n"
                         "with PNG files named: king  queen  rook  bishop  knight  pawn",
                 bg=TK_BG, fg=TK_DIM, font=_font(9), justify="left").pack(anchor="w", pady=(0, 10))

        lf = tk.Frame(F, bg=TK_SURF, bd=0, highlightthickness=1, highlightbackground=TK_BORD)
        lf.pack(fill="x", pady=(0, 6))
        sb = tk.Scrollbar(lf, orient="vertical")
        self._lb = tk.Listbox(lf, yscrollcommand=sb.set, height=7, bg=TK_SURF, fg=TK_TXT,
                              selectbackground=TK_SURF2, selectforeground=TK_GOLD,
                              font=_font(10), relief="flat", bd=0, activestyle="none",
                              highlightthickness=0, exportselection=False)
        sb.config(command=self._lb.yview)
        sb.pack(side="right", fill="y"); self._lb.pack(side="left", fill="both", expand=True)
        self._lb.bind("<<ListboxSelect>>", self._on_sel)
        self._refresh_list()

        self._path_var = tk.StringVar(value="")
        tk.Label(F, textvariable=self._path_var, bg=TK_BG, fg=TK_DIM,
                 font=_font(8), anchor="w", wraplength=440).pack(fill="x", pady=(0, 2))
        self._prev_cv = tk.Canvas(F, bg=TK_BG, height=20, highlightthickness=0)
        self._prev_cv.pack(fill="x", pady=(0, 10))

        br1 = tk.Frame(F, bg=TK_BG); br1.pack(fill="x", pady=(0, 4))
        for lbl, cmd in [("Add Pack…", self._add), ("Create Pack…", self._create_pack), ("Remove", self._remove)]:
            tk.Button(br1, text=lbl, command=cmd, **BS).pack(side="left", padx=(0, 4))
        br2 = tk.Frame(F, bg=TK_BG); br2.pack(fill="x")
        tk.Button(br2, text="Open Folder", command=self._open_folder, **BS).pack(side="left", padx=(0, 4))
        tk.Button(br2, text="Use Selected", command=self._use_selected,
                  **dict(BS, bg="#142A1A", fg="#70D890")).pack(side="left", padx=(0, 4))
        tk.Button(br2, text="Use Default", command=self._use_default, **BS).pack(side="left")

    def _pack_names(self): return [k for k in self._cfg if not k.startswith("__")]

    def _refresh_list(self):
        self._lb.delete(0, "end"); active = self._cfg.get("__active__", "")
        self._lb.insert("end", "  [default] Fancy Chess built-in")
        for name in self._pack_names():
            folder = self._cfg[name]
            ok = "OK" if (os.path.isdir(os.path.join(folder, "white")) and
                          os.path.isdir(os.path.join(folder, "black"))) else "ERR"
            star = " *" if name == active else "  "
            self._lb.insert("end", f"  [{ok}]{star} {name}")

    def _on_sel(self, _=None):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx == 0:
            root = _default_pack_root(); self._path_var.set(f"Path: {root or '(not found)'}"); self._draw_preview(root)
        else:
            names = self._pack_names()
            if idx - 1 < len(names):
                path = self._cfg[names[idx - 1]]
                self._path_var.set(f"Path: {path}"); self._draw_preview(path)

    def _draw_preview(self, folder):
        c = self._prev_cv; c.delete("all")
        if not folder: return
        names = ["king", "queen", "rook", "bishop", "knight", "pawn"]; x = 4
        for sub in ["white", "black"]:
            for pn in names:
                exists = os.path.isfile(os.path.join(folder, sub, f"{pn}.png"))
                fill = "#50C870" if exists else "#503030"
                c.create_rectangle(x, 2, x + 18, 18, fill=fill, outline="")
                c.create_text(x + 9, 10, text=pn[0].upper(),
                              fill="#DDDDDD" if exists else "#885555", font=_font(6, bold=True))
                x += 22
            x += 8
        c.create_text(x, 10, text="green=found  red=missing", fill=TK_DIM, font=_font(7), anchor="w")

    def _add(self):
        folder = filedialog.askdirectory(title="Select pack folder", parent=self)
        if not folder: return
        if not (os.path.isdir(os.path.join(folder, "white")) and
                os.path.isdir(os.path.join(folder, "black"))):
            messagebox.showerror("Invalid Pack",
                                 "Folder must contain 'white' and 'black' subdirectories.", parent=self); return
        name = os.path.basename(folder); base = name; i = 2
        while name in self._cfg: name = f"{base}_{i}"; i += 1
        self._cfg[name] = folder; _save_packs_cfg(self._cfg); self._refresh_list()
        messagebox.showinfo("Pack Added", f"Pack '{name}' added.", parent=self)

    def _create_pack(self):
        pack_name = simpledialog.askstring("Create Pack", "Enter a name for the new pack:", parent=self)
        if not pack_name or not pack_name.strip(): return
        pack_name = pack_name.strip()
        if pack_name in self._cfg:
            messagebox.showerror("Name Taken", f"A pack named '{pack_name}' already exists.", parent=self); return
        dest_parent = filedialog.askdirectory(
            title=f"Choose parent folder — '{pack_name}' subfolder will be created inside", parent=self)
        if not dest_parent: return
        dest = os.path.join(dest_parent, pack_name)
        try:
            os.makedirs(os.path.join(dest, "white"), exist_ok=True)
            os.makedirs(os.path.join(dest, "black"), exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create folders:\n{e}", parent=self); return
        src_root = _default_pack_root(); copied = 0
        if src_root:
            for sub in ["white", "black"]:
                for pn in ["king", "queen", "rook", "bishop", "knight", "pawn"]:
                    src = os.path.join(src_root, sub, f"{pn}.png")
                    dst = os.path.join(dest, sub, f"{pn}.png")
                    if os.path.isfile(src) and not os.path.isfile(dst):
                        try: shutil.copy2(src, dst); copied += 1
                        except Exception: pass
        self._cfg[pack_name] = dest; _save_packs_cfg(self._cfg); self._refresh_list()
        messagebox.showinfo("Pack Created",
                            f"Pack '{pack_name}' created.\n{copied}/12 starter images copied.", parent=self)

    def _remove(self):
        sel = self._lb.curselection()
        if not sel or sel[0] == 0: return
        names = self._pack_names(); idx = sel[0] - 1
        if idx < len(names):
            name = names[idx]
            if not messagebox.askyesno("Remove Pack",
                                       f"Remove '{name}' from list?\n(Files will NOT be deleted)", parent=self): return
            if self._cfg.get("__active__") == name: self._cfg["__active__"] = ""
            del self._cfg[name]; _save_packs_cfg(self._cfg); self._refresh_list(); self._prev_cv.delete("all")

    def _open_folder(self):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        folder = _default_pack_root() if idx == 0 else self._cfg.get(
            self._pack_names()[idx - 1] if idx - 1 < len(self._pack_names()) else "", "")
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Open Folder", "Folder not found.", parent=self); return
        try:
            if sys.platform == "win32": os.startfile(folder)
            elif sys.platform == "darwin": os.system(f'open "{folder}"')
            else: os.system(f'xdg-open "{folder}"')
        except Exception as e:
            log.warning("Open folder error: %s", e)

    def _use_selected(self):
        sel = self._lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx == 0: self._use_default(); return
        names = self._pack_names()
        if idx - 1 < len(names):
            name = names[idx - 1]; self._cfg["__active__"] = name
            _save_packs_cfg(self._cfg); self._refresh_list()
            if self._on_pack_reload: self._on_pack_reload()
            messagebox.showinfo("Pack Active", f"Now using pack: {name}", parent=self)

    def _use_default(self):
        self._cfg["__active__"] = ""; _save_packs_cfg(self._cfg); self._refresh_list()
        if self._on_pack_reload: self._on_pack_reload()
        messagebox.showinfo("Default Pack", "Now using default piece images.", parent=self)


# ─────────────────────────────────────────────────────────────────────────────
# Board Setup window
# ─────────────────────────────────────────────────────────────────────────────
class BoardEditWindow(tk.Toplevel):
    """
    Interactive board editor for setting up custom positions.
    Coordinates: a-h left→right on bottom, 1-8 bottom→top on left.
    Supports FEN import/export.
    """
    CELL = 72

    def __init__(self, master, board, piece_types, tk_icons, accent, on_apply):
        super().__init__(master)
        self.title("Board Setup — Fancy Chess")
        self.configure(bg=TK_BG); self.resizable(False, False); self.grab_set()
        self._work_board = board.clone()
        self._piece_types = piece_types
        self._tk_icons = tk_icons
        self._accent = accent
        self._on_apply = on_apply
        self._sel = None
        self._palette_pos = []; self._img_refs = []; self._board_img_refs = []
        self._stm_var    = tk.IntVar(value=board.current_player)
        self._castle_WK  = tk.BooleanVar(value=board.castling_rights.get((0, 'K'), True))
        self._castle_WQ  = tk.BooleanVar(value=board.castling_rights.get((0, 'Q'), True))
        self._castle_BK  = tk.BooleanVar(value=board.castling_rights.get((1, 'K'), True))
        self._castle_BQ  = tk.BooleanVar(value=board.castling_rights.get((1, 'Q'), True))
        self._ep_var     = tk.StringVar(value="-")
        self._fen_var    = tk.StringVar()
        self._build()
        self.update_idletasks()
        px = master.winfo_x() + (master.winfo_width() - self.winfo_width()) // 2
        py = master.winfo_y() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")
        print("[INFO gui] BoardEditWindow opened")

    def _build(self):
        C = self.CELL
        BS = dict(bg=TK_SURF2, fg=TK_TXT, relief="flat", font=_font(10),
                  padx=10, pady=4, cursor="hand2",
                  activebackground=TK_SURF, activeforeground=TK_TXT, bd=0)
        outer = tk.Frame(self, bg=TK_BG, padx=12, pady=12); outer.pack(fill="both", expand=True)
        tk.Label(outer, text="Board Setup", bg=TK_BG, fg=TK_TXT,
                 font=_font(13, bold=True)).pack(anchor="w", pady=(0, 2))
        tk.Label(outer, text="Left-click palette piece → click square to place   Right-click square to erase",
                 bg=TK_BG, fg=TK_DIM, font=_font(9)).pack(anchor="w", pady=(0, 8))

        row_frame = tk.Frame(outer, bg=TK_BG); row_frame.pack(fill="both", expand=True)
        left = tk.Frame(row_frame, bg=TK_BG); left.pack(side="left", fill="y", padx=(0, 12))
        right = tk.Frame(row_frame, bg=TK_BG); right.pack(side="left", fill="both")

        tk.Label(left, text="PALETTE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        self._pal = tk.Canvas(left, bg=TK_SURF, highlightthickness=1, highlightbackground=TK_BORD)
        self._pal.pack(anchor="w", pady=(2, 12))
        self._pal.bind("<Button-1>", self._pal_click)

        tk.Label(left, text="SIDE TO MOVE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        stm_r = tk.Frame(left, bg=TK_BG); stm_r.pack(anchor="w", pady=(0, 10))
        for lbl, val in [("White", 0), ("Black", 1)]:
            tk.Radiobutton(stm_r, text=lbl, variable=self._stm_var, value=val,
                           bg=TK_BG, fg=TK_TXT, selectcolor=TK_SURF2,
                           activebackground=TK_BG, font=_font(10)).pack(side="left", padx=(0, 10))

        tk.Label(left, text="CASTLING RIGHTS", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        cf = tk.Frame(left, bg=TK_BG); cf.pack(anchor="w", pady=(0, 10))
        opts = [("White O-O", self._castle_WK), ("White O-O-O", self._castle_WQ),
                ("Black O-O", self._castle_BK), ("Black O-O-O", self._castle_BQ)]
        for i, (lbl, var) in enumerate(opts):
            tk.Checkbutton(cf, text=lbl, variable=var, bg=TK_BG, fg=TK_TXT,
                           selectcolor=TK_SURF2, activebackground=TK_BG,
                           font=_font(9), cursor="hand2").grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 8))

        tk.Label(left, text="EN PASSANT FILE", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        ttk.Combobox(left, textvariable=self._ep_var, state="readonly",
                     values=["-", "a", "b", "c", "d", "e", "f", "g", "h"],
                     font=_font(10), width=6).pack(anchor="w", pady=(0, 12))

        tk.Label(left, text="FEN", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        fe = tk.Frame(left, bg=TK_BG); fe.pack(fill="x", pady=(0, 8))
        tk.Entry(fe, textvariable=self._fen_var, bg=TK_SURF2, fg=TK_TXT,
                 insertbackground=TK_TXT, relief="flat", font=_font(8), width=22).pack(side="left", fill="x", expand=True)
        tk.Button(fe, text="Load", command=self._load_fen, **dict(BS, padx=5, pady=2)).pack(side="left", padx=(4, 0))

        tk.Label(left, text="QUICK FILL", bg=TK_BG, fg=TK_DIM, font=_font(8)).pack(anchor="w")
        tk.Button(left, text="Standard Start", command=self._reset,
                  **dict(BS, bg="#1A2A3A", fg="#80B0D8")).pack(fill="x", pady=2)
        tk.Button(left, text="Clear All", command=self._clear,
                  **dict(BS, bg="#2E0E0E", fg="#E08080")).pack(fill="x", pady=2)

        tk.Frame(left, bg=TK_BORD, height=1).pack(fill="x", pady=8)
        tk.Button(left, text="Apply Position", command=self._apply,
                  **dict(BS, bg="#142A1A", fg="#70D890")).pack(fill="x", pady=2)
        tk.Button(left, text="Cancel", command=self.destroy, **BS).pack(fill="x", pady=2)

        # Board canvas with coordinate margin
        # MARGIN left = rank labels (22px), MARGIN bottom = file labels (22px)
        MARGIN = 22
        board_w = C * 8 + MARGIN; board_h = C * 8 + MARGIN
        self._bc = tk.Canvas(right, width=board_w, height=board_h, bg="#101018",
                             highlightthickness=1, highlightbackground=TK_BORD)
        self._bc.pack()
        self._bc.bind("<Button-1>", self._bc_left)
        self._bc.bind("<Button-3>", self._bc_right)
        self._MARGIN = MARGIN
        self._draw_palette(); self._draw_board()

    def _draw_palette(self):
        C = self.CELL; GAP = 4
        names = list(self._piece_types.keys()); ncols = max(len(names), 1)
        self._pal.config(width=ncols * (C + GAP) + GAP, height=2 * (C + GAP) + GAP)
        self._pal.delete("all"); self._palette_pos.clear(); self._img_refs.clear()
        for oi, owner in enumerate([0, 1]):
            for ci, name in enumerate(names):
                pt = self._piece_types[name]; sym = pt.symbol
                x = GAP + ci * (C + GAP); y = GAP + oi * (C + GAP)
                sel = (self._sel == (name, owner))
                self._pal.create_rectangle(x, y, x + C, y + C,
                                           fill="#3A2808" if sel else TK_SURF2,
                                           outline=self._accent if sel else TK_BORD, width=2)
                img = self._tk_icons.get((sym, owner))
                if img:
                    self._img_refs.append(img)
                    self._pal.create_image(x + C // 2, y + C // 2, image=img, anchor="center")
                else:
                    fc = "#D0CCC0" if owner == 0 else "#302C28"
                    self._pal.create_oval(x + 8, y + 8, x + C - 8, y + C - 8, fill=fc, outline="")
                    self._pal.create_text(x + C // 2, y + C // 2, text=sym,
                                          fill="#181818" if owner == 0 else "#D8D8D8",
                                          font=_font(15, bold=True))
                self._pal.create_text(x + C - 5, y + 5, text="W" if owner == 0 else "B",
                                      anchor="ne", fill=TK_DIM, font=_font(7))
                self._palette_pos.append((name, owner, x, y))

    def _pal_click(self, event):
        C = self.CELL
        for (name, owner, x, y) in self._palette_pos:
            if x <= event.x < x + C and y <= event.y < y + C:
                self._sel = None if self._sel == (name, owner) else (name, owner)
                self._draw_palette(); return
        self._sel = None; self._draw_palette()

    def _draw_board(self):
        """
        Draw the board with correct coordinates:
          Rank labels 1-8 on the left margin (1 at bottom, 8 at top)
          File labels a-h on the bottom margin (a at left, h at right)
        row=0 → rank 1 (bottom of visual board = high y)
        row=7 → rank 8 (top of visual board = low y)
        """
        C = self.CELL; M = self._MARGIN
        self._bc.delete("all"); self._board_img_refs = []
        SQ_L = "#E8EAD0"; SQ_D = "#5A8C4E"

        for row in range(8):          # row=0 = rank 1 = bottom
            for col in range(8):
                # Visual y: row 0 is at bottom → y = (7-row)*C
                x = M + col * C; y = (7 - row) * C
                lt = (row + col) % 2 == 0
                self._bc.create_rectangle(x, y, x + C, y + C,
                                          fill=SQ_L if lt else SQ_D, outline="")
                # Rank label: left margin, one per row
                # row+1 = rank number; placed vertically centred in the row
                if col == 0:
                    self._bc.create_text(M // 2, y + C // 2,
                                         text=str(row + 1), anchor="center",
                                         fill="#A0A8B8", font=_font(8, bold=True))
                # File label: bottom margin, one per column
                # col=0 → 'a', col=7 → 'h'; drawn at row==0 strip only
                if row == 0:
                    self._bc.create_text(x + C // 2, 8 * C + M // 2,
                                         text="abcdefgh"[col], anchor="center",
                                         fill="#A0A8B8", font=_font(8, bold=True))
                p = self._work_board.get(row, col)
                if p:
                    sym = p.piece_type.symbol; img = self._tk_icons.get((sym, p.owner))
                    if img:
                        self._board_img_refs.append(img)
                        self._bc.create_image(x + C // 2, y + C // 2, image=img, anchor="center")
                    else:
                        fc2 = "#E8E4DC" if p.owner == 0 else "#2A2826"
                        self._bc.create_oval(x + 5, y + 5, x + C - 5, y + C - 5,
                                             fill=fc2, outline="#808090", width=2)
                        self._bc.create_text(x + C // 2, y + C // 2, text=sym,
                                             fill="#181818" if p.owner == 0 else "#D8D8D8",
                                             font=_font(15, bold=True))

    def _bc_coords(self, event):
        """Convert canvas click to (row,col). row=0=rank1=bottom."""
        C = self.CELL; M = self._MARGIN
        col = (event.x - M) // C
        row = 7 - (event.y // C)   # y=0 → top → row=7 (rank 8); y=7*C → row=0 (rank 1)
        return row, col

    def _bc_left(self, event):
        row, col = self._bc_coords(event)
        if not self._work_board.in_bounds(row, col): return
        if self._sel:
            name, owner = self._sel; pt = self._piece_types[name]
            p = Piece(pt, owner, row, col)
            self._work_board.grid[row][col] = p
            self._draw_board()

    def _bc_right(self, event):
        row, col = self._bc_coords(event)
        if self._work_board.in_bounds(row, col):
            self._work_board.grid[row][col] = None
            self._draw_board()

    def _reset(self):
        self._work_board = Board(8, 8); pt = self._piece_types
        order = ["Rook", "Knight", "Bishop", "Queen", "King", "Bishop", "Knight", "Rook"]
        for c, name in enumerate(order):
            if name in pt:
                self._work_board.place(Piece(pt[name], 0, 0, c))
                self._work_board.place(Piece(pt[name], 1, 7, c))
        for c in range(8):
            if "Pawn" in pt:
                self._work_board.place(Piece(pt["Pawn"], 0, 1, c))
                self._work_board.place(Piece(pt["Pawn"], 1, 6, c))
        self._draw_board()
        print("[INFO gui] Board reset to standard start")

    def _clear(self):
        self._work_board = Board(8, 8); self._draw_board()
        print("[INFO gui] Board cleared")

    def _load_fen(self):
        if not _FEN_SUPPORTED:
            messagebox.showwarning(
                "FEN Not Supported",
                "Your logic.py does not export parse_fen().\n"
                "Please update logic.py to the latest version to enable FEN import.",
                parent=self)
            return
        fen = self._fen_var.get().strip()
        if not fen: return
        try:
            b = parse_fen(fen, self._piece_types)
            self._work_board = b; self._draw_board()
            print(f"[INFO gui] FEN loaded: {fen[:40]}")
        except Exception as e:
            messagebox.showerror("FEN Error", f"Could not parse FEN:\n{e}", parent=self)

    def _apply(self):
        b = self._work_board.clone()
        b.current_player = self._stm_var.get()
        b.castling_rights = {
            (0, 'K'): self._castle_WK.get(), (0, 'Q'): self._castle_WQ.get(),
            (1, 'K'): self._castle_BK.get(), (1, 'Q'): self._castle_BQ.get(),
        }
        ep = self._ep_var.get()
        if ep != "-":
            ep_col = ord(ep) - ord('a')
            ep_row = 5 if b.current_player == 1 else 2
            b.en_passant_target = (ep_row, ep_col)
        self._on_apply(b); self.destroy()
        print("[INFO gui] Board setup applied")


# ─────────────────────────────────────────────────────────────────────────────
# Material tray
# ─────────────────────────────────────────────────────────────────────────────
class MaterialTray(tk.Canvas):
    ICON = 18; PAD = 1

    def __init__(self, master, **kw):
        super().__init__(master, height=(self.ICON + 6) * 2 + 10,
                         bg=TK_PANEL, highlightthickness=0, **kw)
        self._tk_icons = {}; self._img_refs = []
        self._cap_white = []; self._cap_black = []

    def set_icons(self, icons): self._tk_icons = icons

    def refresh(self, board, initial_counts=None):
        if initial_counts is None:
            initial_counts = {}
            for sym in ["K", "Q", "R", "B", "N", "P"]:
                cnt = {"K": 1, "Q": 1, "R": 2, "B": 2, "N": 2, "P": 8}[sym]
                initial_counts[(sym, 0)] = cnt; initial_counts[(sym, 1)] = cnt
        on_board = {}
        for p in board.all_pieces():
            k = (p.piece_type.symbol, p.owner)
            on_board[k] = on_board.get(k, 0) + 1
        self._cap_white = []; self._cap_black = []
        for (sym, owner), sc in initial_counts.items():
            missing = max(0, sc - on_board.get((sym, owner), 0))
            if owner == 1: self._cap_white.extend([sym] * missing)
            else:          self._cap_black.extend([sym] * missing)
        key = lambda s: -PIECE_CP.get(s, 0)
        self._cap_white.sort(key=key); self._cap_black.sort(key=key)
        self._redraw()

    def _redraw(self):
        self.delete("all"); self._img_refs.clear()
        ISZ = self.ICON; PAD = self.PAD; row_h = ISZ + 6

        def cp_sum(syms): return sum(PIECE_CP.get(s, 0) for s in syms)

        adv_w = cp_sum(self._cap_white) - cp_sum(self._cap_black)
        for row_idx, (caps, owner, label) in enumerate([
            (self._cap_white, 1, "White takes"),
            (self._cap_black, 0, "Black takes"),
        ]):
            base_y = row_idx * (row_h + 10)
            self.create_text(4, base_y + 2, text=label, anchor="nw",
                             fill=TK_DIM, font=_font(7))
            icon_y = base_y + 13; x = 4
            for sym in caps:
                img = self._tk_icons.get((sym, owner))
                if img:
                    self._img_refs.append(img)
                    self.create_image(x + ISZ // 2, icon_y + ISZ // 2, image=img, anchor="center")
                else:
                    fc = "#C8C4BE" if owner == 0 else "#383634"
                    self.create_oval(x, icon_y, x + ISZ, icon_y + ISZ, fill=fc, outline="")
                    self.create_text(x + ISZ // 2, icon_y + ISZ // 2, text=sym,
                                     fill="#181818" if owner == 0 else "#D8D8D8",
                                     font=_font(7, bold=True))
                x += ISZ + PAD
            if row_idx == 0 and adv_w > 50:
                self.create_text(x + 4, icon_y + ISZ // 2, anchor="w",
                                 text=f"+{adv_w // 100}", fill=TK_GOLD, font=_font(8, bold=True))
            elif row_idx == 1 and adv_w < -50:
                self.create_text(x + 4, icon_y + ISZ // 2, anchor="w",
                                 text=f"+{-adv_w // 100}", fill=TK_GOLD, font=_font(8, bold=True))


# ─────────────────────────────────────────────────────────────────────────────
# Tkinter side panel
# ─────────────────────────────────────────────────────────────────────────────
class ChessPanel(tk.Frame):
    def __init__(self, master, game, **kw):
        super().__init__(master, bg=TK_PANEL, width=PANEL_W, **kw)
        self.game = game; self.pack_propagate(False)
        self._accent_var = tk.StringVar(value="Gold")
        self._ml_tags = []; self._eval_score = 0
        self._eval_mate = None; self._eval_result = None
        self._build()

    def _btn(self, parent, text, cmd, bg=TK_SURF2, fg=TK_TXT, **kw):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      relief="flat", bd=0, activebackground=TK_SURF,
                      activeforeground=TK_TXT, font=_font(10),
                      padx=8, pady=5, cursor="hand2", **kw)
        b.bind("<Enter>", lambda e: b.config(bg=TK_SURF))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _sep(self): tk.Frame(self, bg=TK_BORD, height=1).pack(fill="x", padx=10, pady=5)
    def _sec(self, t): tk.Label(self, text=t, bg=TK_PANEL, fg=TK_DIM, font=_font(9)).pack(anchor="w", padx=12, pady=(6, 1))

    def _build(self):
        PAD = dict(padx=10, pady=2)

        self._sec("GAME MODE")
        self.mode_var = tk.StringVar(value="Human vs AI")
        mode_cb = ttk.Combobox(self, textvariable=self.mode_var, state="readonly",
                               values=["Human vs Human", "Human vs AI", "AI vs AI"],
                               font=_font(10))
        mode_cb.pack(fill="x", **PAD)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.game.on_mode_change())

        self._sec("AI STRENGTH")
        self.elo_var = tk.StringVar()
        elo_opts = [f"Elo {p['elo']}  {p['name']}" for p in ELO_LEVELS]
        self.elo_var.set(elo_opts[4])
        elo_cb = ttk.Combobox(self, textvariable=self.elo_var, state="readonly",
                              values=elo_opts, font=_font(10))
        elo_cb.pack(fill="x", **PAD)

        self._sec("ACCENT")
        theme_cb = ttk.Combobox(self, textvariable=self._accent_var, state="readonly",
                                values=list(ACCENTS.keys()), font=_font(10))
        theme_cb.pack(fill="x", **PAD)
        theme_cb.bind("<<ComboboxSelected>>", lambda e: self.game.on_accent_change())

        self._sep()
        r1 = tk.Frame(self, bg=TK_PANEL); r1.pack(fill="x", padx=10, pady=2)
        self._btn(r1, "New Game", self.game.new_game).pack(side="left", expand=True, fill="x", padx=(0, 2))
        self._btn(r1, "Undo", self.game.undo).pack(side="left", expand=True, fill="x", padx=(2, 2))
        self._btn(r1, "Edit Pieces", self.game.open_editor).pack(side="left", expand=True, fill="x", padx=(2, 0))

        r2 = tk.Frame(self, bg=TK_PANEL); r2.pack(fill="x", padx=10, pady=2)
        self._btn(r2, "Board Setup", self.game.open_board_edit, bg="#1A1A32", fg="#88AAEE").pack(side="left", expand=True, fill="x", padx=(0, 2))
        self._btn(r2, "Packs", self.game.open_packs, bg="#1A1A32", fg="#88AAEE").pack(side="left", expand=True, fill="x", padx=(2, 2))
        self._btn(r2, "Flip (F)", self.game.flip_board, bg="#1A1A32", fg="#88AAEE").pack(side="left", expand=True, fill="x", padx=(2, 0))

        r3 = tk.Frame(self, bg=TK_PANEL); r3.pack(fill="x", padx=10, pady=2)
        for lbl, cmd in [("|<", lambda: self.game.go_to(0)), ("<", self.game.go_prev),
                         (">", self.game.go_next), (">|", self.game.go_last)]:
            self._btn(r3, lbl, cmd, bg=TK_SURF).pack(side="left", expand=True, fill="x", padx=1)

        r4 = tk.Frame(self, bg=TK_PANEL); r4.pack(fill="x", padx=10, pady=2)
        self._btn(r4, "Load FEN", self.game.load_fen_dialog, bg="#1A2A1A", fg="#80D890").pack(side="left", expand=True, fill="x", padx=(0, 2))
        self._btn(r4, "Copy FEN", self.game.copy_fen, bg="#1A1A2A", fg="#8090D8").pack(side="left", expand=True, fill="x", padx=(2, 0))

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = tk.Label(self, textvariable=self.status_var, bg=TK_PANEL, fg=TK_TXT,
                                   font=_font(10, bold=True))
        self.status_lbl.pack(fill="x", padx=10, pady=(4, 0))

        self._sep()
        self._sec("EVALUATION")
        eval_row = tk.Frame(self, bg=TK_PANEL); eval_row.pack(fill="x", padx=10, pady=(0, 2))
        self.eval_canvas = tk.Canvas(eval_row, height=24, bg=TK_SURF2, highlightthickness=0)
        self.eval_canvas.pack(side="left", fill="x", expand=True)
        self.eval_canvas.bind("<Configure>", lambda e: self._redraw_eval())
        self._badge_var = tk.StringVar(value="")
        self._badge_lbl = tk.Label(eval_row, textvariable=self._badge_var, bg=TK_PANEL,
                                   fg=TK_GOLD, font=_font(10, bold=True), width=6)
        self._badge_lbl.pack(side="left", padx=(4, 0))

        self._sep()
        self._sec("MATERIAL")
        self.material = MaterialTray(self); self.material.pack(fill="x", padx=10, pady=(0, 4))

        self._sep()
        tk.Label(self, text="Right-click: highlight   Drag: arrow   Left-click: erase",
                 bg=TK_PANEL, fg=TK_DIM, font=_font(8), wraplength=PANEL_W - 20).pack(fill="x", padx=10, pady=(0, 2))

        self._sec("MOVES")
        ml_f = tk.Frame(self, bg=TK_PANEL); ml_f.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        scr = tk.Scrollbar(ml_f, orient="vertical")
        self.movelist = tk.Listbox(ml_f, yscrollcommand=scr.set, bg=TK_SURF, fg=TK_TXT,
                                   selectbackground=TK_SURF2, selectforeground=TK_TXT,
                                   font=_font(10, mono=True), relief="flat", bd=0,
                                   activestyle="none", highlightthickness=0, exportselection=False)
        scr.config(command=self.movelist.yview)
        scr.pack(side="right", fill="y"); self.movelist.pack(side="left", fill="both", expand=True)
        self.movelist.bind("<<ListboxSelect>>", self._on_ml_click)
        tk.Label(self, text="Arrow keys or click move to navigate  |  F = flip board",
                 bg=TK_PANEL, fg=TK_DIM, font=_font(8)).pack(pady=(0, 6))

    def set_status(self, text, color=TK_TXT):
        self.status_var.set(text); self.status_lbl.config(fg=color)

    def set_eval(self, score, mate=None, result=None):
        self._eval_score = score; self._eval_mate = mate; self._eval_result = result
        self._redraw_eval(); self._update_badge()

    def _update_badge(self):
        """
        Update the small eval badge label above the move list.
        Convention: mate > 0 = current player mates (green), mate < 0 = opponent (red).
        """
        result = self._eval_result
        mate   = self._eval_mate
        if result:
            self._badge_var.set(result)
            colour = TK_GOLD if result in ("1-0", "0-1") else TK_DIM
        elif mate is not None:
            # Show M{n} — how many full moves until forced checkmate
            self._badge_var.set(f"M{abs(mate)}")
            colour = "#50E080" if mate > 0 else "#E05050"
        else:
            self._badge_var.set("")
            colour = TK_DIM
        self._badge_lbl.config(fg=colour)

    def _redraw_eval(self):
        """
        Redraw the horizontal eval bar in the panel.
        Bar leans white-side when white is ahead (positive score).
        Mate positions show full tilt with M{n} label.
        """
        c  = self.eval_canvas
        w  = c.winfo_width() or (PANEL_W - 30)
        h  = 24
        c.delete("all")
        mate = self._eval_mate
        if mate is not None:
            sc = 2000 if mate > 0 else -2000   # full tilt toward mating side
        else:
            sc = max(-2000, min(2000, self._eval_score))
        split = int(w * (0.5 - sc / 4000.0))
        c.create_rectangle(0, 0, split, h, fill="#232323", outline="")
        c.create_rectangle(split, 0, w, h, fill="#CCCCCC", outline="")

        if self._eval_result:
            etxt   = self._eval_result
            edark  = "#AAAAAA"; elight = "#444444"
        elif mate is not None:
            etxt   = f"M{abs(mate)}"
            # Green for the mating side, red for the mated side
            edark  = "#F07070" if mate < 0 else "#70F070"
            elight = "#CC3333" if mate < 0 else "#228822"
        else:
            val    = self._eval_score / 100.0
            etxt   = f"+{val:.1f}" if val > 0 else f"{val:.1f}"
            edark  = "#AAAAAA"; elight = "#444444"

        if split > w // 2:
            c.create_text(6, h // 2, text=etxt, anchor="w",
                          fill=edark,  font=_font(8, bold=True))
        else:
            c.create_text(w - 6, h // 2, text=etxt, anchor="e",
                          fill=elight, font=_font(8, bold=True))

    def update_movelist(self, san_rec, cursor, result_badge=""):
        self.movelist.delete(0, "end"); self._ml_tags = []; i = 0
        while i < len(san_rec):
            n = i // 2 + 1
            w = san_rec[i] if i < len(san_rec) else ""
            b = san_rec[i + 1] if i + 1 < len(san_rec) else ""
            row_txt = f"  {n:>3}.  {w:<10}  {b}"
            if result_badge and i + 2 >= len(san_rec):
                row_txt = row_txt.rstrip() + f"   {result_badge}"
            self.movelist.insert("end", row_txt)
            self._ml_tags.append(i + 1); i += 2
        cur_row = max(0, (cursor - 1) // 2)
        if cur_row < self.movelist.size():
            self.movelist.selection_clear(0, "end")
            self.movelist.selection_set(cur_row)
            self.movelist.see(cur_row)

    def _on_ml_click(self, ev):
        sel = self.movelist.curselection()
        if not sel: return
        idx = sel[0]; tag = self._ml_tags[idx] if idx < len(self._ml_tags) else idx * 2 + 1
        self.game.go_to(tag)

    def get_mode(self):       return self.mode_var.get()
    def get_accent_hex(self): return ACCENTS.get(self._accent_var.get(), TK_GOLD)
    def get_accent_rgb(self):
        h = self.get_accent_hex().lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    def get_elo_idx(self):
        val = self.elo_var.get()
        for i, p in enumerate(ELO_LEVELS):
            if str(p["elo"]) in val: return i
        return 4

    @staticmethod
    def apply_theme(root):
        style = ttk.Style(root); style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=TK_SURF2, background=TK_SURF2,
                        foreground=TK_TXT, selectbackground=TK_SURF2,
                        selectforeground=TK_TXT, bordercolor=TK_BORD,
                        lightcolor=TK_BORD, darkcolor=TK_BORD, arrowcolor=TK_DIM)
        style.map("TCombobox",
                  fieldbackground=[("readonly", TK_SURF2)],
                  selectbackground=[("readonly", TK_SURF2)],
                  selectforeground=[("readonly", TK_TXT)])
        style.configure("TScrollbar", background=TK_SURF2, troughcolor=TK_SURF,
                        bordercolor=TK_SURF, arrowcolor=TK_DIM)


# ─────────────────────────────────────────────────────────────────────────────
# Board canvas frame (Tkinter wrapper around the pygame embed)
# ─────────────────────────────────────────────────────────────────────────────
class BoardCanvas(tk.Frame):
    """
    Hosts the pygame rendering surface via SDL_WINDOWID.
    Also renders static Tkinter coordinate labels:
      Rank labels 1-8 in the LEFT margin  (1=bottom, 8=top)
      File labels a-h in the BOTTOM margin (a=left, h=right)
    """

    def __init__(self, master, game, **kw):
        # Total frame: board + left rank margin + bottom file margin + eval bar
        total_w = BOARD_PX + COORD_M + EVAL_W + 4
        total_h = BOARD_PX + COORD_M
        super().__init__(master, width=total_w, height=total_h, bg=TK_BG, **kw)
        self.game = game; self.pack_propagate(False)

        # Pygame embed: x=COORD_M (leaves room for rank labels), y=0
        self._embed = tk.Frame(self, width=BOARD_PX, height=BOARD_PX, bg="black")
        self._embed.place(x=COORD_M, y=0)
        self._embed.bind("<Button-1>",        self._on_left)
        self._embed.bind("<Button-3>",        self._on_right_press)
        self._embed.bind("<ButtonRelease-3>", self._on_right_release)
        self._embed.bind("<B3-Motion>",       self._on_right_drag)

        # Vertical eval bar (right of board)
        self.eval_canvas = tk.Canvas(self, width=EVAL_W, height=BOARD_PX,
                                     bg="#1A1A1A", highlightthickness=0)
        self.eval_canvas.place(x=COORD_M + BOARD_PX + 4, y=0)

        # ── Rank labels: 1-8, left margin, bottom-to-top ──────────────────────
        # row i (0-indexed from top) = rank (8-i)
        # y-position: row i → y = i*CELL, centre = i*CELL + CELL//2
        # But rank 1 is at the visual BOTTOM (row index 7 from top)
        # So rank r is at row (8-r) from top → y = (8-r)*CELL - CELL//2
        for rank in range(1, 9):
            y = (8 - rank) * CELL + CELL // 2  # vertical centre of rank r
            tk.Label(self, text=str(rank), bg=TK_BG, fg="#6A8A6A",
                     font=_font(8, bold=True), width=2).place(x=2, y=y - 8)

        # ── File labels: a-h, bottom margin, left-to-right ────────────────────
        for i in range(8):
            ch = "abcdefgh"[i]
            x = COORD_M + i * CELL + CELL // 2
            tk.Label(self, text=ch, bg=TK_BG, fg="#6A8A6A",
                     font=_font(8, bold=True), width=1).place(x=x - 6, y=BOARD_PX + 3)

        self._rclick_start = None

    def draw_eval_bar(self, score, mate=None, result=None):
        """
        Redraw the vertical evaluation bar on the right side of the board.
        mate > 0 = current player mates in N  (green)
        mate < 0 = opponent mates in N         (red)
        """
        c = self.eval_canvas; h = BOARD_PX
        c.delete("all")
        # Clamp score for bar fill; mate positions show full-bar tilt
        if mate is not None:
            sc = 2000 if mate > 0 else -2000
        else:
            sc = max(-2000, min(2000, score))
        split = int(h * (0.5 - sc / 4000.0))
        c.create_rectangle(0, 0, EVAL_W, split, fill="#1C1C1C", outline="")
        c.create_rectangle(0, split, EVAL_W, h, fill="#C8C8C8", outline="")
        if result:
            etxt = result; ecol = "#C8B560"
        elif mate is not None:
            # M{n} where n = number of moves to checkmate
            etxt = f"M{abs(mate)}"
            ecol = "#5EF07A" if mate > 0 else "#F05E5E"  # green=current player, red=opponent
        else:
            val = score / 100.0
            etxt = f"+{val:.1f}" if val > 0 else f"{val:.1f}"
            ecol = "#888888"
        c.create_text(EVAL_W // 2, h // 2, text=etxt, anchor="center",
                      fill=ecol, font=_font(8, bold=True), angle=90)

    def _on_left(self, event):
        erased = self.game.annot_erase(event.x, event.y)
        if not erased:
            if self.game.promo_move: self.game._promo_click(event.x, event.y)
            else:                    self.game._board_click(event.x, event.y)

    def _on_right_press(self, event):
        row, col = self.game._px_cell(event.x, event.y)
        if self.game.board.in_bounds(row, col):
            self._rclick_start = (row, col, event.x, event.y)

    def _on_right_drag(self, event):
        if self._rclick_start:
            _, _, x0, y0 = self._rclick_start
            self.game.annot_drag_preview = (x0, y0, event.x, event.y)

    def _on_right_release(self, event):
        self.game.annot_drag_preview = None
        if self._rclick_start is None: return
        r0, c0, x0, y0 = self._rclick_start; self._rclick_start = None
        row, col = self.game._px_cell(event.x, event.y)
        if not self.game.board.in_bounds(row, col): return
        if (row, col) == (r0, c0): self.game.annot_toggle_highlight(row, col)
        else:                      self.game.annot_toggle_arrow((r0, c0), (row, col))

    def get_embed_id(self):
        self._embed.update(); return self._embed.winfo_id()


# ─────────────────────────────────────────────────────────────────────────────
# Main game class
# ─────────────────────────────────────────────────────────────────────────────
class FancyChess:
    """
    Main application controller.
    Owns: root Tk window, pygame loop, board state, AI threads, animations.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Fancy Chess")
        self.root.configure(bg=TK_BG)
        self.root.resizable(False, False)
        ChessPanel.apply_theme(self.root)
        self.flipped = False

        self.annot_highlights  = {}
        self.annot_arrows      = {}
        self.annot_drag_preview = None

        self.board_canvas = BoardCanvas(self.root, self)
        self.board_canvas.pack(side="left", fill="both")
        self.panel = ChessPanel(self.root, self)
        self.panel.pack(side="left", fill="both")

        # ── Pygame init (embedded into Tkinter frame) ─────────────────────────
        if _PYGAME_OK:
            embed_id = self.board_canvas.get_embed_id()
            os.environ["SDL_WINDOWID"] = str(embed_id)
            if sys.platform == "win32":
                os.environ["SDL_VIDEODRIVER"] = "windib"
            elif sys.platform.startswith("linux"):
                os.environ["SDL_VIDEODRIVER"] = "x11"
            pygame.init()
            _init_overlays()   # pre-bake all SRCALPHA overlay surfaces once
            # Surface covers exactly the board area (no coord margin — labels are Tkinter)
            self.pg_surf = pygame.display.set_mode((BOARD_PX, BOARD_PX))
            self.clock = pygame.time.Clock()
            print(f"[INFO gui] Pygame surface created: {BOARD_PX}x{BOARD_PX}")
        else:
            self.pg_surf = None; self.clock = None
            print("[WARN gui] pygame not available — board rendering disabled")

        self._coord_font = None
        self.sounds = SoundSystem()

        self.imgs         = load_images(CELL)  # pre-scaled to exact draw_sz internally
        self.tk_icons     = load_tk_icons(52)
        self.tk_icons_sm  = load_tk_icons(MaterialTray.ICON)
        self.panel.material.set_icons(self.tk_icons_sm)

        self.piece_types = build_default_pieces()
        self.gen = MoveGenerator()
        self._init_game_state()

        # Keyboard shortcuts
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
        print("[INFO gui] FancyChess initialised, starting main loop")

    # ── Game state ──────────────────────────────────────────────────────────
    def _init_game_state(self, custom_board=None):
        if custom_board is not None:
            self.board = custom_board
        else:
            self.board = Board(8, 8); pt = self.piece_types
            order = ["Rook", "Knight", "Bishop", "Queen", "King", "Bishop", "Knight", "Rook"]
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
        self.anim_checkmate = None
        self.board_hist = [self.board.clone()]
        self.flip_hist  = [self.flipped]   # parallel list: flipped state at each board_hist entry
        self.move_rec = []; self.san_rec = []
        self.nav_cur = 0; self.navigating = False
        self.ai_thinking = False; self.ai_thread = None
        self.eval_score = 0; self.last_ai_t = 0; self._checked_kings = []
        self.annot_highlights = {}; self.annot_arrows = {}; self.annot_drag_preview = None
        self._update_panel()
        print("[INFO gui] Game state initialised")

    # ── Annotation helpers ───────────────────────────────────────────────────
    def annot_toggle_highlight(self, row, col):
        key = (row, col); cur = self.annot_highlights.get(key, -1); nxt = cur + 1
        if nxt >= len(ANNOT_COLORS): del self.annot_highlights[key]
        else:                        self.annot_highlights[key] = nxt

    def annot_toggle_arrow(self, from_sq, to_sq):
        key = (from_sq, to_sq)
        if key in self.annot_arrows: del self.annot_arrows[key]
        else:                        self.annot_arrows[key] = 0

    def annot_erase(self, x, y):
        row, col = self._px_cell(x, y); erased = False
        if (row, col) in self.annot_highlights:
            del self.annot_highlights[(row, col)]; erased = True
        to_del = [k for k in self.annot_arrows if k[0] == (row, col) or k[1] == (row, col)]
        for k in to_del: del self.annot_arrows[k]; erased = True
        return erased

    def annot_clear(self):
        self.annot_highlights.clear(); self.annot_arrows.clear()
        self.annot_drag_preview = None

    # ── Coordinate helpers ───────────────────────────────────────────────────
    def _cell_px(self, row, col):
        """
        Return top-left pixel (x,y) of cell (row,col) on the pygame surface.
        row=0 (rank 1) → visual bottom (y = 7*CELL)
        row=7 (rank 8) → visual top    (y = 0)
        col=0 (file a) → visual left   (x = 0)
        col=7 (file h) → visual right  (x = 7*CELL)
        When flipped, the board is rotated 180°.
        """
        if self.flipped:
            return (7 - col) * CELL, row * CELL
        return col * CELL, (7 - row) * CELL

    def _px_cell(self, x, y):
        """Map pixel coordinates from the pygame embed to (row,col)."""
        if self.flipped:
            return y // CELL, 7 - x // CELL
        return (7 - y // CELL), x // CELL

    def _cell_center(self, row, col):
        x, y = self._cell_px(row, col)
        return x + CELL // 2, y + CELL // 2

    # ── Mode helpers ─────────────────────────────────────────────────────────
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
        self._init_game_state()
        print("[INFO gui] New game started")

    def flip_board(self):
        self.flipped = not self.flipped
        print(f"[INFO gui] Board flipped: {self.flipped}")

    # ── Board setup / packs ──────────────────────────────────────────────────
    def open_board_edit(self):
        BoardEditWindow(self.root, self.board, self.piece_types,
                        self.tk_icons, self.panel.get_accent_hex(),
                        on_apply=self._apply_board_edit)

    def _apply_board_edit(self, board):
        self._init_game_state(custom_board=board)
        print("[INFO gui] Custom board position applied")

    def open_packs(self):
        PackManagerWindow(self.root, on_pack_reload=self._reload_pack)

    def _reload_pack(self):
        self.imgs        = load_images(CELL)  # pre-scaled to exact draw_sz internally
        self.tk_icons    = load_tk_icons(52)
        self.tk_icons_sm = load_tk_icons(MaterialTray.ICON)
        self.panel.material.set_icons(self.tk_icons_sm)
        print("[INFO gui] Pack reloaded")

    def open_editor(self):
        try:
            from piece_editor import PieceEditorWindow
            PieceEditorWindow(self.root, dict(self.piece_types),
                              on_save_cb=self._on_editor_save)
        except Exception as e:
            log.exception("Editor open error")
            messagebox.showerror("Editor Error", str(e))

    def _on_editor_save(self, new_types):
        self.piece_types = new_types
        self._init_game_state()
        print(f"[INFO gui] Piece types updated: {list(new_types.keys())}")

    # ── FEN ──────────────────────────────────────────────────────────────────
    def load_fen_dialog(self):
        """
        Open a proper FEN import dialog with a text entry field.
        Supports standard FEN strings (6 fields or abbreviated).
        Shows validation errors inline before applying.
        """
        if not _FEN_SUPPORTED:
            messagebox.showwarning(
                "FEN Not Supported",
                "Your logic.py does not export parse_fen().\n"
                "Please update logic.py to the latest version.",
                parent=self.root)
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Load FEN Position")
        dlg.configure(bg=TK_BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        # Centre over main window
        self.root.update_idletasks()
        rx = self.root.winfo_rootx() + self.root.winfo_width()  // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2
        dlg.geometry(f"500x180+{rx - 250}+{ry - 90}")

        tk.Label(dlg, text="Paste a FEN string below and click Load:",
                 bg=TK_BG, fg=TK_TXT, font=_font(10)).pack(pady=(14, 4), padx=16, anchor="w")

        fen_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=fen_var, bg=TK_SURF2, fg=TK_TXT,
                         insertbackground=TK_TXT, relief="flat", font=_font(10),
                         width=58, highlightthickness=1,
                         highlightcolor=TK_GOLD, highlightbackground=TK_BORD)
        entry.pack(padx=16, fill="x")
        entry.focus_set()

        # Pre-fill with current position FEN for easy editing
        try:
            fen_var.set(to_fen(self.board))
            entry.select_range(0, "end")
        except Exception:
            pass

        err_lbl = tk.Label(dlg, text="", bg=TK_BG, fg="#F06060", font=_font(9))
        err_lbl.pack(pady=(4, 0), padx=16, anchor="w")

        def _load():
            fen = fen_var.get().strip()
            if not fen:
                err_lbl.config(text="Please enter a FEN string.")
                return
            try:
                b = parse_fen(fen, self.piece_types)
                self._init_game_state(custom_board=b)
                print(f"[INFO gui] FEN loaded: {fen[:60]}")
                dlg.destroy()
            except Exception as e:
                err_lbl.config(text=f"Invalid FEN: {e}")
                log.warning("FEN parse error: %s", e)

        def _on_enter(ev):
            _load()

        entry.bind("<Return>", _on_enter)

        btn_row = tk.Frame(dlg, bg=TK_BG)
        btn_row.pack(pady=12, padx=16, fill="x")
        tk.Button(btn_row, text="Load", command=_load,
                  bg="#1A3A1A", fg="#80D890", relief="flat", font=_font(10, bold=True),
                  padx=14, pady=4, cursor="hand2", bd=0).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=TK_SURF2, fg=TK_TXT, relief="flat", font=_font(10),
                  padx=14, pady=4, cursor="hand2", bd=0).pack(side="left")

        dlg.wait_window()

    def copy_fen(self):
        if not _FEN_SUPPORTED:
            messagebox.showwarning(
                "FEN Not Supported",
                "Your logic.py does not export to_fen().\n"
                "Please update logic.py to the latest version to enable FEN export.",
                parent=self.root)
            return
        try:
            fen = to_fen(self.board)
            self.root.clipboard_clear(); self.root.clipboard_append(fen)
            self.panel.set_status("FEN copied!", TK_GOLD)
            self.root.after(2000, lambda: self.panel.set_status(""))
            print(f"[INFO gui] FEN copied: {fen[:40]}")
        except Exception as e:
            log.exception("FEN export error")

    # ── Navigation ───────────────────────────────────────────────────────────
    def go_to(self, idx):
        if not self.board_hist: return
        idx = max(0, min(idx, len(self.board_hist) - 1))
        self.nav_cur = idx
        self.board = self.board_hist[idx].clone()
        self.navigating = (idx < len(self.board_hist) - 1)
        self.selected = None; self.legal_moves = []
        self._update_panel()

    def go_prev(self):  self.go_to(self.nav_cur - 1)
    def go_next(self):  self.go_to(self.nav_cur + 1)
    def go_last(self):
        self.go_to(len(self.board_hist) - 1); self.navigating = False

    def undo(self):
        if len(self.board_hist) < 2: return
        self.board_hist.pop()
        # Restore the board-orientation that was active before this move
        if len(self.flip_hist) > 1:
            self.flip_hist.pop()        # discard the post-move entry
            self.flipped = self.flip_hist[-1]   # restore pre-move orientation
        self.move_rec and self.move_rec.pop()
        self.san_rec and self.san_rec.pop()
        self.nav_cur = len(self.board_hist) - 1
        self.board = self.board_hist[-1].clone()
        self.game_over = False; self.game_over_msg = ""; self.result_badge = ""
        self.anim_checkmate = None; self.anim_mate = None
        self.selected = None; self.legal_moves = []; self.navigating = False
        self._check_over(); self._update_panel()
        print(f"[INFO gui] Move undone — flipped={self.flipped}")

    # ── AI ────────────────────────────────────────────────────────────────────
    def trigger_ai(self):
        if self.ai_thinking or self.game_over or self.anim_move or self.promo_move: return
        if self.navigating: self.go_last(); return
        self.ai_thinking = True; self.panel.set_status("AI thinking…", TK_DIM)
        snap = self.board; owner = snap.current_player; idx = self._elo_idx()

        def worker():
            mv = get_best_move(snap, owner, elo_idx=idx)
            self.ai_thinking = False
            if mv:
                # Clear "thinking" status immediately so UI feels responsive
                self.root.after(0, lambda: self.panel.set_status(""))
                self.anim_queue.append(mv)
            else:
                self.root.after(0, lambda: self.panel.set_status("AI has no moves", TK_DIM))
                self._check_over()

        self.ai_thread = threading.Thread(target=worker, daemon=True)
        self.ai_thread.start()

    # ── SAN notation ─────────────────────────────────────────────────────────
    def _san(self, move, board_before):
        """
        Convert a move to Standard Algebraic Notation using logic.MoveGenerator.
        Produces proper SAN like Nf3, exd5, O-O, e8=Q, Rxd1+, Qh5#.
        Falls back to coordinate style on any error.
        """
        try:
            return self.gen.move_to_san(move, board_before)
        except Exception as e:
            # Fallback: simple coordinate notation
            log.debug("SAN error: %s", e)
            fr, fc = move["from_pos"]; tr, tc = move["to_pos"]
            f = "abcdefgh"
            cap = "x" if move.get("captured_uid") else ""
            return f"{f[fc]}{fr+1}{cap}{f[tc]}{tr+1}"

    # ── Apply move ────────────────────────────────────────────────────────────
    def _apply(self, move, animate=True):
        """
        Apply a move to the board.
        Determines sound type, starts animations, updates state,
        and plays the appropriate synthesised sound.
        """
        if self.navigating: self.go_last()
        fr, fc = move["from_pos"]; tr, tc = move["to_pos"]
        piece = self.board.get(fr, fc)
        if not piece: return
        self.annot_clear()

        # Determine move type for sound (must be done BEFORE board update)
        is_capture = bool(move.get("captured_uid"))
        is_castle  = bool(move.get("castling"))

        # Start capture fade animation
        if move.get("captured_uid"):
            cap_pos = move.get("en_passant_capture") or (tr, tc)
            for p in self.board.all_pieces():
                if p.uid == move["captured_uid"]:
                    cpx, cpy = self._cell_px(*cap_pos)
                    self.anim_fades.append(FadePiece(p, cpx, cpy)); break

        # Promotion: show picker if human, auto-queen for AI
        if move.get("needs_promotion") and not move.get("promotion_type"):
            auto = ("AI" in self._mode() and self.board.current_player != 0) or self._mode() == "AI vs AI"
            if auto:
                move = dict(move); move["promotion"] = "Queen"
                move["promotion_type"] = self.piece_types.get("Queen")
            else:
                self.promo_move = move
                self.promo_opts = move.get("promotion_options", ["Queen", "Rook", "Bishop", "Knight"])
                if animate:
                    self.anim_move = MovingPiece(piece, self._cell_px(fr, fc), self._cell_px(tr, tc))
                return

        if animate:
            self.anim_move = MovingPiece(piece, self._cell_px(fr, fc), self._cell_px(tr, tc))

        san = self._san(move, self.board)
        self.board = self.board.apply_move(move)
        self.board_hist.append(self.board.clone())
        # Record the flipped state that will be active AFTER this move.
        # In Human vs Human mode the board auto-flips 300ms later; we snapshot
        # the post-flip value by toggling here and recording it, then the actual
        # flip() call from after() becomes a no-op (or we skip it).
        # Simpler approach: store PRE-MOVE flip; undo restores it perfectly.
        self.flip_hist.append(self.flipped)
        self.move_rec.append(move); self.san_rec.append(san)
        self.nav_cur = len(self.board_hist) - 1
        self.last_move = move; self.selected = None; self.legal_moves = []

        # Play sound based on move type (check/checkmate override in _check_over)
        if is_castle:    self.sounds.play("castle")
        elif is_capture: self.sounds.play("capture")
        else:            self.sounds.play("move")

        # Defer _check_over and _async_eval so the first animation frame renders
        # before we do expensive legal-move generation. after(0) yields to Tk's
        # event loop immediately, so the sliding animation starts without a hitch.
        self.root.after(0, self._check_over)
        self.root.after(0, self._async_eval)
        self._update_panel()

    # ── Check / game-over ─────────────────────────────────────────────────────
    def _check_over(self):
        """
        After each move: check for checkmate/stalemate/draw,
        play appropriate sound (check or checkmate), start animations.
        """
        result = self.gen.game_result(self.board)
        if result:
            self.game_over = True; cp = self.board.current_player
            winner = "Black" if cp == 0 else "White"
            msgs = {
                "checkmate":  f"Checkmate — {winner} wins",
                "stalemate":  "Stalemate — Draw",
                "50move":     "Draw — 50-move rule",
                "repetition": "Draw — Threefold repetition",
                "material":   "Draw — Insufficient material",
            }
            self.game_over_msg = msgs.get(result, "Game over")
            col = TK_GOLD if "wins" in self.game_over_msg else TK_DIM
            self.root.after(0, lambda: self.panel.set_status(self.game_over_msg, col))

            if result == "checkmate":
                self.result_badge = "0-1" if cp == 0 else "1-0"
                king = self.board.find_king(cp)
                if king:
                    self.anim_mate = MatePulse(king.row, king.col)
                    self.anim_checkmate = CheckmateAnim(king.row, king.col)
                self.sounds.play("checkmate")
                print(f"[INFO gui] Checkmate! {self.result_badge}")
            else:
                self.result_badge = "1/2"; self.anim_draw = DrawFlash()

            self.root.after(0, lambda rb=self.result_badge: (
                self.panel.set_eval(self.eval_score, result=rb),
                self.board_canvas.draw_eval_bar(self.eval_score, result=rb),
            ))
        else:
            self.result_badge = ""; cp = self.board.current_player
            in_chk = self.gen.is_in_check(self.board, cp)
            name = "White" if cp == 0 else "Black"
            txt = f"{name} in CHECK" if in_chk else f"{name} to move"
            col = TK_RED if in_chk else TK_TXT
            self.root.after(0, lambda t=txt, c=col: self.panel.set_status(t, c))
            if in_chk:
                self.sounds.play("check")
                print(f"[INFO gui] Check on {name}")

        # Update checked kings list for red highlight
        self._checked_kings = []
        for owner in [0, 1]:
            if self.gen.is_in_check(self.board, owner):
                king = self.board.find_king(owner)
                if king: self._checked_kings.append((king.row, king.col))

    def _update_panel(self):
        def _do():
            self.panel.update_movelist(self.san_rec, self.nav_cur, self.result_badge)
            self.panel.material.refresh(self.board)
        self.root.after(0, _do)

    def _async_eval(self):
        """
        Background thread: evaluate position and search for forced mate.

        mate_n convention used throughout:
          > 0  →  the current player to move (owner) has a forced mate in mate_n moves
          < 0  →  the opponent has a forced mate in abs(mate_n) moves
          None →  no forced mate detected in search budget

        The eval bar renders M{abs(mate_n)} in green (current player mates) or
        red (opponent mates) so the display is always from the viewer's perspective.
        """
        snap  = self.board
        owner = snap.current_player     # 0=white, 1=black

        def worker():
            try:
                score = quick_eval(snap, 0)
                self.eval_score = score
                mate_n = None

                # Mate-in-N search (up to 5 moves, 3 s budget)
                if not self.game_over:
                    # Try current player first
                    n, _mv = find_mate_in_n(snap, owner, max_n=5, deadline_secs=1.5)
                    if n is not None:
                        # Current player can force mate in n
                        mate_n = n          # positive → current player mates
                        print(f"[gui] Mate in {n} for '{'White' if owner==0 else 'Black'}'")
                    else:
                        # Check if opponent has a forced mate
                        n2, _mv2 = find_mate_in_n(snap, 1 - owner, max_n=5, deadline_secs=1.0)
                        if n2 is not None:
                            mate_n = -n2    # negative → opponent mates
                            print(f"[gui] Opponent mate in {n2}")

                self.root.after(0, lambda s=score, m=mate_n: (
                    self.panel.set_eval(s, mate=m),
                    self.board_canvas.draw_eval_bar(s, mate=m),
                ))
            except Exception:
                log.exception("Async eval error")

        threading.Thread(target=worker, daemon=True).start()

    # ── Board click ───────────────────────────────────────────────────────────
    def _board_click(self, x, y):
        """Handle left-click on the board — select piece or execute move."""
        if self.game_over or self.anim_move or self.ai_thinking or self.promo_move: return
        if x >= BOARD_PX: return
        row, col = self._px_cell(x, y)
        if not self.board.in_bounds(row, col): return
        if self.navigating: self.go_last(); return
        if not self._human_turn(): return

        clicked = self.board.get(row, col)
        if self.selected:
            mv = next((m for m in self.legal_moves if m["to_pos"] == (row, col)), None)
            if mv:
                self._apply(mv)
                mode = self._mode()
                if not self.game_over and mode == "Human vs AI":
                    self.root.after(350, self.trigger_ai)
                elif mode == "Human vs Human" and not self.game_over:
                    self.root.after(300, self.flip_board)
                return
            self.selected = None; self.legal_moves = []
            if clicked and clicked.owner == self.board.current_player: pass
            else: self.anim_shake = ShakeAnim(row, col); return
        if clicked and clicked.owner == self.board.current_player:
            self.selected = clicked
            self.legal_moves = self.gen.get_moves(clicked, self.board, legal_only=True)
        else:
            self.anim_shake = ShakeAnim(row, col)

    def _promo_click(self, x, y):
        """Handle click on the promotion picker overlay."""
        if not self.promo_move: return
        n = len(self.promo_opts); bw, bh = 82, 96
        bx = BOARD_PX // 2 - n * bw // 2; by = BOARD_PX // 2 - bh // 2
        for i, name in enumerate(self.promo_opts):
            r = pygame.Rect(bx + i * bw, by, bw - 4, bh)
            if r.collidepoint(x, y):
                mv = dict(self.promo_move)
                mv["promotion"] = name; mv["promotion_type"] = self.piece_types.get(name)
                self.promo_move = None; bb = self.board
                self.board = self.board.apply_move(mv)
                self.board_hist.append(self.board.clone())
                self.move_rec.append(mv); self.san_rec.append(self._san(mv, bb))
                self.nav_cur = len(self.board_hist) - 1
                self.last_move = mv; self.selected = None
                self.sounds.play("promotion")
                self._check_over(); self._async_eval(); self._update_panel()
                if not self.game_over and self._mode() == "Human vs AI":
                    self.root.after(350, self.trigger_ai)
                print(f"[INFO gui] Promotion: {name}")
                return

    # ── Pygame tick loop ──────────────────────────────────────────────────────
    def _pg_tick(self):
        if not self._running: return
        if not _PYGAME_OK:
            self.root.after(50, self._pg_tick); return

        now = time.time(); dt = min(now - self._prev_time, 0.05); self._prev_time = now

        for ev in pygame.event.get():
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.promo_move: self._promo_click(*ev.pos)
                else:               self._board_click(*ev.pos)

        self._update_anims(dt)

        # AI vs AI auto-play
        if (self._mode() == "AI vs AI" and not self.game_over and not self.ai_thinking
                and not self.anim_move and not self.promo_move
                and not self.anim_queue and not self.navigating):
            if now - self.last_ai_t > 0.5:
                self.last_ai_t = now; self.trigger_ai()

        if self.anim_queue and not self.anim_move and not self.promo_move:
            self._apply(self.anim_queue.pop(0))

        self._draw()
        pygame.display.flip()
        # Schedule next frame without blocking — clock.tick() would stall
        # Tkinter's event loop for the full frame time, making the UI sluggish.
        # after(16) targets ~60 fps without starving other Tk callbacks.
        self.root.after(16, self._pg_tick)

    def _update_anims(self, dt):
        """Advance all active animations by dt seconds."""
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
        if self.anim_checkmate:
            self.anim_checkmate.update(dt)
            if self.anim_checkmate.done: self.anim_checkmate = None

    # ── Pygame draw ───────────────────────────────────────────────────────────
    def _draw(self):
        acc = self.panel.get_accent_rgb()
        # Blit the pre-baked static board (plain squares only) as the base layer.
        # This avoids 64 draw.rect calls every frame. Rebuilt only when orientation changes.
        if not hasattr(self, '_board_bg') or self._board_bg_flipped != self.flipped:
            self._board_bg = pygame.Surface((BOARD_PX, BOARD_PX))
            for row in range(8):
                for col in range(8):
                    x, y = self._cell_px(row, col)
                    self._board_bg.fill(SQ_LIGHT if (row+col)%2==0 else SQ_DARK, (x, y, CELL, CELL))
            self._board_bg_flipped = self.flipped
            print(f"[INFO gui] Board background rebuilt (flipped={self.flipped})")
        self.pg_surf.blit(self._board_bg, (0, 0))
        self._draw_board(self.pg_surf, acc)
        self._draw_annotations(self.pg_surf)
        self._draw_pieces(self.pg_surf)
        if self.anim_checkmate:
            row, col = self.anim_checkmate.row, self.anim_checkmate.col
            cx, cy = self._cell_px(row, col)
            self.anim_checkmate.draw(self.pg_surf, cx, cy)
        self._draw_promo(self.pg_surf, acc)
        self._draw_gameover(self.pg_surf, acc)

    def _draw_board(self, surf, accent_rgb):
        """
        Draw squares + coordinate labels on the pygame surface.

        Performance: all SRCALPHA overlay surfaces are pre-baked in _OV so this
        method does zero Surface allocations at runtime — just blits.
        """
        if not self._coord_font:
            try:    self._coord_font = pygame.font.SysFont("DejaVu Sans", 13, bold=True)
            except Exception: self._coord_font = pygame.font.Font(None, 16)
        font = self._coord_font

        # Pre-compute sets for O(1) lookup instead of scanning lists per cell
        lm_cells  = set()
        if self.last_move:
            lm_cells.add(self.last_move["from_pos"])
            lm_cells.add(self.last_move["to_pos"])
        chk_cells = set(self._checked_kings)
        dot_cells = set(); ring_cells = set()
        for mv in self.legal_moves:
            if mv.get("captured_uid"):  ring_cells.add(mv["to_pos"])
            else:                       dot_cells.add(mv["to_pos"])

        # Pulse surface is rebuilt each frame because alpha changes
        if self.anim_mate:
            _mate_surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
            _mate_surf.fill((*CHK_COL[:3], self.anim_mate.alpha))
        else:
            _mate_surf = None

        # Draw-flash surface shares alpha too
        if self.anim_draw:
            _draw_surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
            _draw_surf.fill((205, 165, 55, self.anim_draw.alpha))
        else:
            _draw_surf = None

        for row in range(8):
            for col in range(8):
                x, y = self._cell_px(row, col)
                ox = self.anim_shake.offset if (
                    self.anim_shake and self.anim_shake.row == row
                    and self.anim_shake.col == col) else 0
                light = (row + col) % 2 == 0
                # Plain square already drawn by _draw() via _board_bg cache.
                # Only redraw if shake offset is non-zero (rare).
                if ox:
                    pygame.draw.rect(surf, SQ_LIGHT if light else SQ_DARK, (x + ox, y, CELL, CELL))

                if (row, col) in lm_cells:   surf.blit(_OV["lm"],  (x, y))
                if _mate_surf and self.anim_mate.row == row and self.anim_mate.col == col:
                    surf.blit(_mate_surf, (x, y))
                if _draw_surf:               surf.blit(_draw_surf, (x, y))
                if (row, col) in chk_cells:  surf.blit(_OV["chk"], (x, y))
                if self.selected and self.selected.row == row and self.selected.col == col:
                    surf.blit(_OV["sel"], (x, y))

                # Legal move dots / capture rings
                cx2 = x + CELL // 2; cy2 = y + CELL // 2
                if   (row, col) in ring_cells: pygame.draw.circle(surf, CAP_COL, (cx2, cy2), CELL // 2 - 3, 4)
                elif (row, col) in dot_cells:  pygame.draw.circle(surf, DOT_COL, (cx2, cy2), CELL // 8)

                # Coordinate labels (only on edge squares)
                if (not self.flipped and col == 0) or (self.flipped and col == 7):
                    rank_num = row + 1 if not self.flipped else 8 - row
                    rs = font.render(str(rank_num), True, COORD_DARK if light else COORD_LIGHT)
                    surf.blit(rs, (x + 3, y + 3))
                if (not self.flipped and row == 0) or (self.flipped and row == 7):
                    file_ch = "abcdefgh"[col] if not self.flipped else "abcdefgh"[7 - col]
                    ls = font.render(file_ch, True, COORD_LIGHT if light else COORD_DARK)
                    surf.blit(ls, (x + CELL - ls.get_width() - 3, y + CELL - ls.get_height() - 3))

        # Navigation overlay banner — reuse pre-baked nav surface
        if self.navigating:
            surf.blit(_OV["nav"], (0, 0))
            msg = f"Move {self.nav_cur}/{len(self.board_hist)-1}  —  click board to resume"
            s = font.render(msg, True, accent_rgb)
            surf.blit(s, (BOARD_PX // 2 - s.get_width() // 2, 6))

    def _draw_annotations(self, surf):
        """Draw right-click highlights and arrows using cached overlay surfaces."""
        _ov_keys = ["annot0", "annot1", "annot2", "annot3"]
        for (row, col), cidx in self.annot_highlights.items():
            x, y = self._cell_px(row, col)
            surf.blit(_OV[_ov_keys[cidx % 4]], (x, y))
        for (from_sq, to_sq), cidx in self.annot_arrows.items():
            cx1, cy1 = self._cell_center(*from_sq); cx2, cy2 = self._cell_center(*to_sq)
            draw_arrow(surf, cx1, cy1, cx2, cy2, ANNOT_COLORS[cidx % len(ANNOT_COLORS)])
        if self.annot_drag_preview:
            x0, y0, x1, y1 = self.annot_drag_preview
            draw_arrow(surf, x0, y0, x1, y1, (255, 255, 255, 110))

    def _draw_pieces(self, surf):
        """Draw all pieces; skip piece currently being animated."""
        auid = self.anim_move.piece.uid if self.anim_move else None
        for fa in self.anim_fades:
            draw_piece(surf, self.imgs, fa.piece, fa.px, fa.py, alpha=fa.alpha, scale=fa.scale)
        for row in range(8):
            for col in range(8):
                p = self.board.get(row, col)
                if p and p.uid != auid:
                    px, py = self._cell_px(row, col)
                    draw_piece(surf, self.imgs, p, px, py)
        if self.anim_move:
            ax, ay = self.anim_move.pos
            draw_piece(surf, self.imgs, self.anim_move.piece, int(ax), int(ay))

    def _draw_promo(self, surf, accent_rgb):
        """Draw promotion picker overlay."""
        if not self.promo_move: return
        n = len(self.promo_opts); bw, bh = 82, 96
        bx = BOARD_PX // 2 - n * bw // 2; by = BOARD_PX // 2 - bh // 2
        ov = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 155)); surf.blit(ov, (0, 0))
        box = pygame.Rect(bx - 18, by - 44, n * bw + 36, bh + 64)
        pygame.draw.rect(surf, (18, 18, 28), box, border_radius=14)
        pygame.draw.rect(surf, accent_rgb, box, 2, border_radius=14)
        try: fn = pygame.font.SysFont("DejaVu Sans", 13)
        except Exception: fn = pygame.font.Font(None, 16)
        title = fn.render("Promote to:", True, accent_rgb)
        surf.blit(title, (box.centerx - title.get_width() // 2, box.y + 10))
        owner = self.board.current_player ^ 1
        for i, name in enumerate(self.promo_opts):
            r = pygame.Rect(bx + i * bw, by, bw - 4, bh)
            pygame.draw.rect(surf, (32, 32, 48), r, border_radius=8)
            pygame.draw.rect(surf, accent_rgb, r, 1, border_radius=8)
            if name in self.piece_types:
                dummy = Piece(self.piece_types[name], owner, 0, 0)
                draw_piece(surf, self.imgs, dummy, r.x, r.y, size=bw - 4, scale=0.82)
            lbl = fn.render(name, True, (200, 200, 216))
            surf.blit(lbl, (r.centerx - lbl.get_width() // 2, r.bottom - 16))

    def _draw_gameover(self, surf, accent_rgb):
        """Draw game-over banner overlay."""
        if not self.game_over: return
        ov = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 125)); surf.blit(ov, (0, 0))
        box = pygame.Rect(BOARD_PX // 2 - 230, BOARD_PX // 2 - 54, 460, 108)
        pygame.draw.rect(surf, (14, 14, 22), box, border_radius=14)
        pygame.draw.rect(surf, accent_rgb, box, 2, border_radius=14)
        try:
            fL = pygame.font.SysFont("DejaVu Sans", 20, bold=True)
            fS = pygame.font.SysFont("DejaVu Sans", 12)
        except Exception:
            fL = pygame.font.Font(None, 26); fS = pygame.font.Font(None, 16)
        badge = f"  [{self.result_badge}]" if self.result_badge else ""
        lbl = fL.render(self.game_over_msg + badge, True, accent_rgb)
        surf.blit(lbl, (box.centerx - lbl.get_width() // 2, box.y + 14))
        sub = fS.render("N  new game       U  undo       F  flip board", True, (90, 90, 112))
        surf.blit(sub, (box.centerx - sub.get_width() // 2, box.y + 60))

    def _on_close(self):
        self._running = False
        if _PYGAME_OK: pygame.quit()
        self.root.destroy()
        print("[INFO gui] Application closed")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    FancyChess().run()

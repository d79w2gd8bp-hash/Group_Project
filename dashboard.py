"""Voter dashboard page: KPI cards, charts and a township / polling-station table.

Charts are drawn on plain Tk canvases (no matplotlib) so Myanmar text renders the same way as
everywhere else in the app and no extra dependency is needed.
"""
import re
import time
import unicodedata
from datetime import datetime
from tkinter import filedialog, ttk
import tkinter as tk
import tkinter.font as tkfont
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from customtkinter import CTkButton, CTkFrame, CTkLabel, CTkOptionMenu, CTkScrollableFrame

ALL_TOWNSHIPS = "မြို့နယ်အားလုံး"
UNKNOWN = "မသတ်မှတ်ရသေး"
AGE_GROUPS: Tuple[Tuple[str, int, int], ...] = (
    ("၁၈ – ၃၉", 18, 39),
    ("၄၀ – ၅၉", 40, 59),
    ("၆၀ နှင့်အထက်", 60, 200),
)
GENDER_LABELS = {"ကျား": "အမျိုးသား", "မ": "အမျိုးသမီး"}

VOTED_COLOR = "#22C55E"
PENDING_COLOR = "#F59E0B"
DANGER_COLOR = "#EF4444"
ACCENT_COLOR = "#3B82F6"
PURPLE_COLOR = "#A855F7"

ANIMATIONS_ENABLED = True   # set False to turn every dashboard animation off
ANIMATION_MS = 800          # full intro animation
FILTER_ANIMATION_MS = 500   # re-animation after choosing a township
FRAME_MS = 30               # ~33 fps: smooth, and leaves the UI thread time to draw the widgets
INTRO_DELAY_MS = 60         # let the page paint once before the intro starts


class _Animator:
    """One timer drives every running animation (KPI counters and charts), so a dashboard full of
    animations costs a single Tk callback per frame instead of one per widget."""

    def __init__(self):
        self._items: Dict[Any, Tuple[float, float, Callable[[float], None]]] = {}
        self._job: Optional[str] = None
        self._widget: Any = None

    def start(self, widget: Any, key: Any, duration: int, update: Callable[[float], None], delay: int = 0):
        self._items[key] = (time.perf_counter() + delay / 1000, max(1, duration), update)
        if self._job is None or self._widget is None or not self._widget.winfo_exists():
            self._widget = widget
            self._job = widget.after(delay, self._tick)

    def cancel(self, key: Any):
        self._items.pop(key, None)

    def _tick(self):
        now = time.perf_counter()
        for key, (started, duration, update) in list(self._items.items()):
            if now < started:
                continue
            t = min(1.0, (now - started) * 1000 / duration)
            try:
                update(ease_out_cubic(t))
            except Exception:  # widget destroyed (e.g. logout) -> drop the animation
                t = 1.0
            if t >= 1.0:
                self._items.pop(key, None)
        if self._items and self._widget is not None and self._widget.winfo_exists():
            self._job = self._widget.after(FRAME_MS, self._tick)
        else:
            self._job = None


ANIMATOR = _Animator()

_TO_MM = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")
_TO_ASCII = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")


# --------------------------------------------------------------------------- helpers
def mm_number(value: float) -> str:
    return f"{int(round(value)):,}".translate(_TO_MM)


def mm_percent(part: float, whole: float) -> str:
    if not whole:
        return "၀%"
    return f"{part / whole * 100:.1f}%".translate(_TO_MM)


def _clean(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value if value is not None else "")).strip()


def _to_int(value: Any) -> Optional[int]:
    match = re.search(r"\d+", _clean(value).translate(_TO_ASCII))
    return int(match.group()) if match else None


def _age_from_birth(value: Any) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", _clean(value).translate(_TO_ASCII))
    return datetime.now().year - int(match.group()) if match else None


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def stagger(progress: float, index: int, count: int, spread: float = 0.35) -> float:
    """Per-item progress so items start one after another (index 0 first)."""
    if count <= 1 or spread <= 0:
        return progress
    start = spread * index / (count - 1)
    return max(0.0, min(1.0, (progress - start) / (1 - spread)))


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def _blend(color: str, background: str, alpha: float) -> str:
    """Mix color into background (alpha = weight of color)."""
    fg = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    bg = [int(background[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


def _round_rect(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, **kwargs) -> int:
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
              x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def prepare_voters(df: pd.DataFrame) -> pd.DataFrame:
    """Normalised frame used by every chart: township, station, voted, criminal, gender, age, age_group."""
    def column(name: str) -> pd.Series:
        return df[name].map(_clean) if name in df.columns else pd.Series([""] * len(df), index=df.index)

    data = pd.DataFrame(index=df.index)
    data["township"] = column("township").replace("", UNKNOWN)
    data["station"] = column("polling_station").replace("", UNKNOWN)
    data["voted"] = column("vote_status").str.lower().isin({"ပြီး", "voted", "yes", "1"})
    data["criminal"] = column("criminal_record").isin({"ရှိ", "yes", "true", "1"})
    data["gender"] = column("gender").map(lambda g: GENDER_LABELS.get(g, g or UNKNOWN))
    ages = column("age").map(_to_int)
    if ages.isna().all() and "date_of_birth" in df.columns:
        ages = df["date_of_birth"].map(_age_from_birth)
    data["age"] = pd.to_numeric(ages, errors="coerce")

    def group(age: float) -> str:
        if pd.isna(age):
            return UNKNOWN
        for label, low, high in AGE_GROUPS:
            if low <= age <= high:
                return label
        return UNKNOWN

    data["age_group"] = data["age"].map(group)
    return data


# --------------------------------------------------------------------------- widgets
class KpiCard(CTkFrame):
    def __init__(self, master, title: str, accent: str, colors: Dict[str, str], family: str):
        super().__init__(master, height=110, fg_color=colors["surface"], corner_radius=14,
                         border_width=1, border_color=colors["border"])
        self.grid_columnconfigure(1, weight=1)
        CTkFrame(self, width=5, height=40, fg_color=accent, corner_radius=3).grid(row=0, column=0, rowspan=3, sticky="ns", padx=(10, 0), pady=14)
        CTkLabel(self, text=title, font=(family, 12), text_color=colors["muted"], anchor="w").grid(
            row=0, column=1, sticky="ew", padx=14, pady=(12, 0))
        self.value = CTkLabel(self, text="-", font=(family, 26, "bold"), text_color=colors["text"], anchor="w")
        self.value.grid(row=1, column=1, sticky="ew", padx=14)
        self.note = CTkLabel(self, text="", font=(family, 11), text_color=accent, anchor="w")
        self.note.grid(row=2, column=1, sticky="ew", padx=14, pady=(0, 12))
        self._shown = 0.0
        self._count_job: Optional[str] = None

    def set(self, value: str, note: str = ""):
        self.value.configure(text=value)
        self.note.configure(text=note)

    def count_to(self, target: float, note: str = "", duration: int = ANIMATION_MS, from_zero: bool = False, delay: int = 0):
        """Count the number up (or down) from the value currently shown to target."""
        self.note.configure(text=note)
        ANIMATOR.cancel(self)
        start_value = 0.0 if from_zero else self._shown
        if not ANIMATIONS_ENABLED or duration <= 0 or start_value == target:
            self._shown = float(target)
            self.value.configure(text=mm_number(target))
            return

        def update(progress: float):
            self._shown = start_value + (target - start_value) * progress
            self.value.configure(text=mm_number(self._shown))

        update(0.0)
        ANIMATOR.start(self, self, duration, update, delay)


class ChartCard(CTkFrame):
    """Card with a title and a canvas that is redrawn on resize."""

    def __init__(self, master, title: str, subtitle: str, height: int, colors: Dict[str, str], family: str):
        super().__init__(master, fg_color=colors["surface"], corner_radius=14,
                         border_width=1, border_color=colors["border"])
        self.colors = colors
        CTkLabel(self, text=title, font=(family, 15, "bold"), text_color=colors["text"], anchor="w").pack(
            fill="x", padx=18, pady=(14, 0))
        self.subtitle = CTkLabel(self, text=subtitle, font=(family, 11), text_color=colors["muted"], anchor="w")
        self.subtitle.pack(fill="x", padx=18, pady=(0, 2))
        self.canvas = tk.Canvas(self, height=height, bg=colors["surface"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.font = tkfont.Font(root=self.canvas, family=family, size=10)
        self.font_small = tkfont.Font(root=self.canvas, family=family, size=9)
        self.font_bold = tkfont.Font(root=self.canvas, family=family, size=10, weight="bold")
        self.font_big = tkfont.Font(root=self.canvas, family=family, size=22, weight="bold")
        self._base_height = height
        self._font_sizes = ((self.font, 10), (self.font_small, 9), (self.font_bold, 10), (self.font_big, 22))
        self._draw_fn: Optional[Callable[["ChartCard", int, int], None]] = None
        self.progress = 1.0          # 0..1, read by the draw functions to grow bars / sweep arcs
        self._anim_job: Optional[str] = None
        self._bound: set = set()     # (tag, sequence) pairs to unbind before each redraw
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

    def set_zoom(self, zoom: float):
        """Ctrl +/- zoom: canvases and their fonts are plain Tk, so scale them here."""
        for font, size in self._font_sizes:
            font.configure(size=max(6, round(size * zoom)))
        self.canvas.configure(height=round(self._base_height * zoom))
        self.redraw()

    def render(self, draw: Callable[["ChartCard", int, int], None], animate_ms: int = 0, delay: int = 0):
        self._draw_fn = draw
        if animate_ms and ANIMATIONS_ENABLED:
            self.animate(animate_ms, delay)
        else:
            ANIMATOR.cancel(self)
            self.progress = 1.0
            self.redraw()

    def animate(self, duration: int = ANIMATION_MS, delay: int = 0):
        def update(progress: float):
            self.progress = progress
            self.redraw()

        update(0.0)
        ANIMATOR.start(self, self, duration, update, delay)

    def redraw(self):
        # Tag bindings outlive deleted items, so drop them before drawing the next frame.
        for tag, sequence in self._bound:
            self.canvas.tag_unbind(tag, sequence)
        self._bound.clear()
        self.canvas.configure(cursor="")
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self._draw_fn and width > 40 and height > 40:
            self._draw_fn(self, width, height)

    # interactive helpers -------------------------------------------------
    def _bind_tag(self, tag: str, sequence: str, callback: Callable[[Any], None]):
        self.canvas.tag_bind(tag, sequence, callback, add="+")
        self._bound.add((tag, sequence))

    def hover(self, tag: str, text: str):
        canvas = self.canvas
        if self.progress < 1:  # no tooltips while bars are still growing
            return
        self._bind_tag(tag, "<Enter>", lambda e: self._tip(e.x, e.y, text))
        self._bind_tag(tag, "<Motion>", lambda e: self._tip(e.x, e.y, text))
        self._bind_tag(tag, "<Leave>", lambda _e: canvas.delete("tip"))

    def clickable(self, tag: str, callback: Callable[[], None]):
        canvas = self.canvas
        self._bind_tag(tag, "<Button-1>", lambda _e: callback())
        self._bind_tag(tag, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
        self._bind_tag(tag, "<Leave>", lambda _e: canvas.configure(cursor=""))

    def highlight(self, tag: str, item: int, normal: str, hot: str):
        """Light up a background item while the mouse is over the tagged group."""
        canvas = self.canvas
        self._bind_tag(tag, "<Enter>", lambda _e: canvas.itemconfigure(item, fill=hot))
        self._bind_tag(tag, "<Leave>", lambda _e: canvas.itemconfigure(item, fill=normal))

    def _tip(self, x: int, y: int, text: str):
        canvas = self.canvas
        canvas.delete("tip")
        label = canvas.create_text(0, 0, text=text, anchor="nw", fill="#F8FAFC", font=self.font, tags="tip")
        x0, y0, x1, y1 = canvas.bbox(label)
        tip_w, tip_h = x1 - x0 + 20, y1 - y0 + 14
        px = x + 16 if x + 16 + tip_w < canvas.winfo_width() else x - tip_w - 12
        py = max(2, min(y - tip_h / 2, canvas.winfo_height() - tip_h - 2))
        _round_rect(canvas, px, py, px + tip_w, py + tip_h, 8, fill="#0F172A", outline="#475569", tags="tip")
        canvas.coords(label, px + 10, py + 7)
        canvas.tag_raise(label)

    def legend(self, items: Sequence[Tuple[str, str]], x: float = 4, y: float = 10):
        for text, color in items:
            _round_rect(self.canvas, x, y - 6, x + 12, y + 6, 3, fill=color, outline="")
            item = self.canvas.create_text(x + 18, y, text=text, anchor="w", fill=self.colors["muted"], font=self.font_small)
            x = self.canvas.bbox(item)[2] + 18

    def empty(self, width: int, height: int):
        self.canvas.create_text(width / 2, height / 2, text="ဒေတာမရှိပါ", fill=self.colors["muted"], font=self.font)


# --------------------------------------------------------------------------- drawing
def draw_stacked_hbars(card: ChartCard, width: int, height: int, rows: List[Dict[str, Any]],
                       selected: str, on_click: Callable[[str], None]):
    """Township bars: voted + not voted, turnout % on the right. Click a bar to filter."""
    canvas, colors = card.canvas, card.colors
    if not rows:
        return card.empty(width, height)
    card.legend([("မဲပေးပြီး", VOTED_COLOR), ("မဲမပေးရသေး", PENDING_COLOR)])
    top = 30
    label_w = min(max(card.font.measure(r["name"]) for r in rows) + 18, width * 0.36)
    x0, x1 = label_w, width - 70
    row_h = (height - top) / len(rows)
    bar_h = min(26, row_h * 0.62)
    max_total = max(r["total"] for r in rows) or 1
    scale = (x1 - x0) / max_total
    for i, row in enumerate(rows):
        rp = stagger(card.progress, i, len(rows))
        yc = top + row_h * (i + 0.5)
        yt, yb = yc - bar_h / 2, yc + bar_h / 2
        active = selected in (ALL_TOWNSHIPS, row["name"])
        alpha = 1.0 if active else 0.28
        tag = f"bar{i}"
        # full-width hover strip behind the row
        strip = canvas.create_rectangle(0, yc - row_h / 2 + 2, width, yc + row_h / 2 - 2, fill=colors["surface"], width=0, tags=tag)
        card.highlight(tag, strip, colors["surface"], _blend(colors["primary"], colors["surface"], 0.12))
        canvas.create_text(x0 - 10, yc, text=row["name"], anchor="e", font=card.font_bold if selected == row["name"] else card.font,
                           fill=colors["text"] if active else colors["muted"], tags=tag)
        _round_rect(canvas, x0, yt, x1, yb, 6, fill=colors["surface_alt"], outline="", tags=tag)
        xv = x0 + row["voted"] * scale * rp
        xn = xv + row["pending"] * scale * rp
        canvas.create_rectangle(x0, yt, xv, yb, fill=_blend(VOTED_COLOR, colors["surface"], alpha), width=0, tags=tag)
        canvas.create_rectangle(xv, yt, xn, yb, fill=_blend(PENDING_COLOR, colors["surface"], alpha), width=0, tags=tag)
        if xv - x0 > 34:
            canvas.create_text((x0 + xv) / 2, yc, text=mm_number(row["voted"] * rp), fill="#052E16", font=card.font_small, tags=tag)
        if xn - xv > 34:
            canvas.create_text((xv + xn) / 2, yc, text=mm_number(row["pending"] * rp), fill="#451A03", font=card.font_small, tags=tag)
        canvas.create_text(x1 + 10, yc, text=mm_percent(row["voted"] * rp, row["total"]), anchor="w",
                           fill=colors["text"] if active else colors["muted"], font=card.font_bold, tags=tag)
        card.hover(tag, f"{row['name']}\nစုစုပေါင်း  {mm_number(row['total'])}\n"
                        f"မဲပေးပြီး  {mm_number(row['voted'])} ({mm_percent(row['voted'], row['total'])})\n"
                        f"မဲမပေးရသေး  {mm_number(row['pending'])}\n(နှိပ်၍ စစ်ထုတ်ရန်)")
        card.clickable(tag, lambda name=row["name"]: on_click(name))


def draw_grouped_vbars(card: ChartCard, width: int, height: int, groups: List[Tuple[str, int, int]]):
    """Voted / not-voted bar pair per group, with turnout under each group label."""
    canvas, colors = card.canvas, card.colors
    if not groups or not any(v + p for _, v, p in groups):
        return card.empty(width, height)
    card.legend([("မဲပေးပြီး", VOTED_COLOR), ("မဲမပေးရသေး", PENDING_COLOR)])
    x0, x1, y0, y1 = 44, width - 6, 40, height - 48
    top_value = _nice_ceiling(max(max(v, p) for _, v, p in groups))
    for k in range(5):
        y = y1 - (y1 - y0) * k / 4
        canvas.create_line(x0, y, x1, y, fill=colors["border"], dash=(2, 4))
        canvas.create_text(x0 - 8, y, text=mm_number(top_value * k / 4), anchor="e", fill=colors["muted"], font=card.font_small)
    group_w = (x1 - x0) / len(groups)
    bar_w = min(48, group_w * 0.3)
    for i, (label, voted, pending) in enumerate(groups):
        gp = stagger(card.progress, i, len(groups))
        cx = x0 + group_w * (i + 0.5)
        for value, color, left, name in ((voted, VOTED_COLOR, cx - bar_w - 3, "မဲပေးပြီး"), (pending, PENDING_COLOR, cx + 3, "မဲမပေးရသေး")):
            tag = f"g{i}{name}"
            yt = y1 - (y1 - y0) * value * gp / top_value
            if y1 - yt >= 1:
                _round_rect(canvas, left, yt, left + bar_w, y1, 5, fill=color, outline="", tags=tag)
                canvas.create_rectangle(left, max(yt, y1 - 5), left + bar_w, y1, fill=color, width=0, tags=tag)
            canvas.create_text(left + bar_w / 2, yt - 9, text=mm_number(value * gp), fill=colors["text"], font=card.font_small, tags=tag)
            card.hover(tag, f"{label}\n{name}  {mm_number(value)}\nအုပ်စုအတွင်း {mm_percent(value, voted + pending)}")
        canvas.create_text(cx, y1 + 14, text=label, fill=colors["text"], font=card.font_bold)
        canvas.create_text(cx, y1 + 34, text=f"မဲပေးမှုနှုန်း {mm_percent(voted * gp, voted + pending)}", fill=colors["muted"], font=card.font_small)


def draw_donut(card: ChartCard, width: int, height: int, voted: int, pending: int):
    canvas, colors = card.canvas, card.colors
    total = voted + pending
    if not total:
        return card.empty(width, height)
    size = min(width * 0.62, height - 64)
    cx, cy, r = width / 2, (height - 52) / 2 + 4, size / 2
    box = (cx - r, cy - r, cx + r, cy + r)
    p = card.progress
    extent = voted / total * 360
    sweep = 360 * p
    canvas.create_oval(*box, fill=colors["surface_alt"], outline="")  # empty track
    if p >= 1 and (voted == total or pending == total):
        canvas.create_oval(*box, fill=VOTED_COLOR if voted else PENDING_COLOR, outline="", tags="v" if voted else "p")
    else:
        voted_sweep = min(extent, sweep)
        pending_sweep = max(0.0, sweep - extent)
        if voted_sweep > 0.5:
            canvas.create_arc(*box, start=90, extent=-min(voted_sweep, 359.9), fill=VOTED_COLOR, outline=colors["surface"], width=2, tags="v")
        if pending_sweep > 0.5:
            canvas.create_arc(*box, start=90 - extent, extent=-min(pending_sweep, 359.9), fill=PENDING_COLOR, outline=colors["surface"], width=2, tags="p")
    inner = r * 0.66
    canvas.create_oval(cx - inner, cy - inner, cx + inner, cy + inner, fill=colors["surface"], outline="")
    canvas.create_text(cx, cy - 12, text=mm_percent(voted * p, total), fill=colors["text"], font=card.font_big)
    canvas.create_text(cx, cy + 24, text="မဲပေးမှုနှုန်း", fill=colors["muted"], font=card.font_small)
    card.hover("v", f"မဲပေးပြီး  {mm_number(voted)} ({mm_percent(voted, total)})")
    card.hover("p", f"မဲမပေးရသေး  {mm_number(pending)} ({mm_percent(pending, total)})")
    legend_y = height - 34
    for j, (text, value, color) in enumerate((("မဲပေးပြီး", voted, VOTED_COLOR), ("မဲမပေးရသေး", pending, PENDING_COLOR))):
        label = f"{text}  {mm_number(value)}"
        lx = width * (0.25 + 0.5 * j) - (card.font_small.measure(label) + 18) / 2
        _round_rect(canvas, lx, legend_y + 4, lx + 12, legend_y + 16, 3, fill=color, outline="")
        canvas.create_text(lx + 18, legend_y + 10, text=label, anchor="w", fill=colors["text"], font=card.font_small)


def draw_stacked_vbars(card: ChartCard, width: int, height: int, bins: List[Tuple[str, int, int]]):
    """Age distribution: stacked voted / not-voted columns per age bin."""
    canvas, colors = card.canvas, card.colors
    if not bins or not any(v + p for _, v, p in bins):
        return card.empty(width, height)
    card.legend([("မဲပေးပြီး", VOTED_COLOR), ("မဲမပေးရသေး", PENDING_COLOR)])
    x0, x1, y0, y1 = 44, width - 6, 34, height - 26
    top_value = _nice_ceiling(max(v + p for _, v, p in bins))
    for k in range(5):
        y = y1 - (y1 - y0) * k / 4
        canvas.create_line(x0, y, x1, y, fill=colors["border"], dash=(2, 4))
        canvas.create_text(x0 - 8, y, text=mm_number(top_value * k / 4), anchor="e", fill=colors["muted"], font=card.font_small)
    slot = (x1 - x0) / len(bins)
    bar_w = max(6, slot * 0.62)
    for i, (label, voted, pending) in enumerate(bins):
        bp = stagger(card.progress, i, len(bins), spread=0.5)
        left = x0 + slot * i + (slot - bar_w) / 2
        y_voted = y1 - (y1 - y0) * voted * bp / top_value
        y_total = y1 - (y1 - y0) * (voted + pending) * bp / top_value
        tag = f"h{i}"
        canvas.create_rectangle(left, y_voted, left + bar_w, y1, fill=VOTED_COLOR, width=0, tags=tag)
        canvas.create_rectangle(left, y_total, left + bar_w, y_voted, fill=PENDING_COLOR, width=0, tags=tag)
        canvas.create_text(left + bar_w / 2, y1 + 13, text=label, fill=colors["muted"], font=card.font_small)
        card.hover(tag, f"အသက် {label}\nစုစုပေါင်း  {mm_number(voted + pending)}\n"
                        f"မဲပေးပြီး  {mm_number(voted)} ({mm_percent(voted, voted + pending)})\nမဲမပေးရသေး  {mm_number(pending)}")


def draw_simple_hbars(card: ChartCard, width: int, height: int, rows: List[Tuple[str, int, int]], color: str, selected: str):
    """Single-series horizontal bars (e.g. criminal records per township). rows: (label, value, total)."""
    canvas, colors = card.canvas, card.colors
    if not rows:
        return card.empty(width, height)
    label_w = min(max(card.font.measure(r[0]) for r in rows) + 18, width * 0.42)
    x0, x1 = label_w, width - 46
    row_h = height / len(rows)
    bar_h = min(20, row_h * 0.55)
    max_value = max(r[1] for r in rows) or 1
    for i, (label, value, total) in enumerate(rows):
        sp = stagger(card.progress, i, len(rows))
        yc = row_h * (i + 0.5)
        active = selected in (ALL_TOWNSHIPS, label)
        tag = f"s{i}"
        canvas.create_text(x0 - 10, yc, text=label, anchor="e", fill=colors["text"] if active else colors["muted"], font=card.font_small, tags=tag)
        _round_rect(canvas, x0, yc - bar_h / 2, x1, yc + bar_h / 2, 5, fill=colors["surface_alt"], outline="", tags=tag)
        if value and sp > 0:
            _round_rect(canvas, x0, yc - bar_h / 2, x0 + (x1 - x0) * value * sp / max_value, yc + bar_h / 2, 5,
                        fill=_blend(color, colors["surface"], 1.0 if active else 0.3), outline="", tags=tag)
        canvas.create_text(x1 + 8, yc, text=mm_number(value * sp), anchor="w", fill=colors["text"], font=card.font_bold, tags=tag)
        card.hover(tag, f"{label}\n{mm_number(value)} ဦး (မဲဆန္ဒရှင်၏ {mm_percent(value, total)})")


# --------------------------------------------------------------------------- page
class DashboardView(CTkFrame):
    def __init__(self, master, colors: Dict[str, str], family: str,
                 get_dataset: Callable[[], pd.DataFrame], get_source_name: Callable[[], str], role: str):
        super().__init__(master, fg_color="transparent")
        self.colors, self.family, self.role = colors, family, role
        self.get_dataset, self.get_source_name = get_dataset, get_source_name
        self.is_admin = role in {"Admin", "Super Admin"}
        self.selected = ALL_TOWNSHIPS
        self.data = pd.DataFrame()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self.body = CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        for col in range(3):
            self.body.grid_columnconfigure(col, weight=1, uniform="dash")
        self._build_body()

    # layout ------------------------------------------------------------------
    def _build_header(self):
        c = self.colors
        header = CTkFrame(self, fg_color=c["surface"], corner_radius=14, border_width=1, border_color=c["border"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        CTkLabel(header, text="မဲဆန္ဒရှင် ခြုံငုံသုံးသပ်ချက်", font=(self.family, 20, "bold"),
                 text_color=c["text"], anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 0))
        self.meta_label = CTkLabel(header, text="", font=(self.family, 11), text_color=c["muted"], anchor="w")
        self.meta_label.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))
        controls = CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=1, rowspan=2, sticky="e", padx=16)
        self.township_menu = CTkOptionMenu(
            controls, values=[ALL_TOWNSHIPS], command=self._select_township, width=200, height=34,
            font=(self.family, 12), dropdown_font=(self.family, 12),
            fg_color=c["surface_alt"], button_color=c["primary"], button_hover_color=c["primary_hover"],
        )
        self.township_menu.pack(side="left", padx=(0, 8))
        CTkButton(controls, text="↻  ပြန်တွက်ရန်", width=110, height=34, command=self.refresh,
                  fg_color=c["surface_alt"], hover_color=c["primary_hover"], border_width=1,
                  border_color=c["border"], font=(self.family, 12)).pack(side="left", padx=(0, 8))
        CTkButton(controls, text="CSV ထုတ်ရန်", width=100, height=34, command=self._export_summary,
                  fg_color=c["primary"], hover_color=c["primary_hover"], font=(self.family, 12)).pack(side="left")

    def _build_body(self):
        c, f = self.colors, self.family
        kpi_row = CTkFrame(self.body, fg_color="transparent")
        kpi_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        kpi_specs = [("total", "စုစုပေါင်း မဲဆန္ဒရှင်", ACCENT_COLOR), ("voted", "မဲပေးပြီးသူ", VOTED_COLOR),
                     ("pending", "မဲမပေးရသေးသူ", PENDING_COLOR)]
        kpi_specs.append(("criminal", "ပြစ်မှုမှတ်တမ်းရှိသူ", DANGER_COLOR) if self.is_admin
                         else ("stations", "မဲရုံ အရေအတွက်", PURPLE_COLOR))
        self.kpis: Dict[str, KpiCard] = {}
        for i, (key, title, accent) in enumerate(kpi_specs):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="kpi")
            card = KpiCard(kpi_row, title, accent, c, f)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == len(kpi_specs) - 1 else 6))
            self.kpis[key] = card

        self.township_chart = ChartCard(self.body, "မြို့နယ်အလိုက် ဆန္ဒမဲပေးမှု", "ဘားကိုနှိပ်၍ မြို့နယ်တစ်ခုချင်းစီ စစ်ထုတ်ကြည့်နိုင်သည်", 300, c, f)
        self.township_chart.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 6), pady=(0, 12))
        self.donut_chart = ChartCard(self.body, "မဲပေးမှုနှုန်း", "", 300, c, f)
        self.donut_chart.grid(row=1, column=2, sticky="nsew", padx=(6, 0), pady=(0, 12))

        self.age_chart = ChartCard(self.body, "အသက်အပိုင်းအခြားအလိုက်", "၁၈–၃၉ • ၄၀–၅၉ • ၆၀ နှင့်အထက်", 280, c, f)
        self.gender_chart = ChartCard(self.body, "ကျား / မ အလိုက်", "", 280, c, f)
        if self.is_admin:
            self.age_chart.grid(row=2, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
            self.gender_chart.grid(row=2, column=1, sticky="nsew", padx=6, pady=(0, 12))
            self.criminal_chart = ChartCard(self.body, "ပြစ်မှုမှတ်တမ်းရှိသူ (မြို့နယ်အလိုက်)", "Admin သာ ကြည့်ရှုနိုင်သည်", 280, c, f)
            self.criminal_chart.grid(row=2, column=2, sticky="nsew", padx=(6, 0), pady=(0, 12))
        else:
            self.criminal_chart = None
            self.age_chart.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=(0, 6), pady=(0, 12))
            self.gender_chart.grid(row=2, column=2, sticky="nsew", padx=(6, 0), pady=(0, 12))

        self.histogram_chart = ChartCard(self.body, "အသက်အလိုက် ဖြန့်ကျက်မှု", "အသက် ၅ နှစ်ခြား အုပ်စုအလိုက်", 230, c, f)
        self.histogram_chart.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(0, 12))
        self._build_table(row=4)
        self._chart_cards = [card for card in (self.township_chart, self.donut_chart, self.age_chart, self.gender_chart,
                                               self.criminal_chart, self.histogram_chart) if card is not None]
        self._zoom = 1.0

    def _build_table(self, row: int):
        c, f = self.colors, self.family
        card = CTkFrame(self.body, fg_color=c["surface"], corner_radius=14, border_width=1, border_color=c["border"])
        card.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(0, 12))
        CTkLabel(card, text="မြို့နယ် / မဲရုံ အလိုက် အနှစ်ချုပ်ဇယား", font=(f, 15, "bold"),
                 text_color=c["text"], anchor="w").pack(fill="x", padx=18, pady=(14, 0))
        CTkLabel(card, text="မြို့နယ်ကိုဖွင့်၍ မဲရုံအလိုက် ကြည့်ရှုနိုင်သည်", font=(f, 11),
                 text_color=c["muted"], anchor="w").pack(fill="x", padx=18, pady=(0, 8))

        style = ttk.Style(self)
        if style.theme_use() not in {"clam", "alt", "default"}:
            style.theme_use("clam")
        style.configure("Dash.Treeview", background=c["surface"], fieldbackground=c["surface"], foreground=c["text"], borderwidth=0)
        style.configure("Dash.Treeview.Heading", background=c["surface_alt"], foreground=c["muted"],
                        relief="flat", borderwidth=0, padding=(8, 8))
        style.map("Dash.Treeview", background=[("selected", c["primary"])], foreground=[("selected", "#FFFFFF")])
        style.map("Dash.Treeview.Heading", background=[("active", c["border"])])
        style.layout("Dash.Treeview", [("Dash.Treeview.treearea", {"sticky": "nswe"})])

        columns = ["total", "voted", "pending", "rate"] + (["criminal"] if self.is_admin else [])
        headings = {"total": "စုစုပေါင်း", "voted": "မဲပေးပြီး", "pending": "မဲမပေးရသေး", "rate": "မဲပေးမှုနှုန်း", "criminal": "ပြစ်မှုရှိ"}
        self.table = ttk.Treeview(card, columns=columns, style="Dash.Treeview", height=9, selectmode="browse")
        self.table.heading("#0", text="မြို့နယ် / မဲရုံ", anchor="w")
        self.table.column("#0", width=260, minwidth=180, anchor="w", stretch=True)
        for key in columns:
            self.table.heading(key, text=headings[key], anchor="center")
            self.table.column(key, width=110, minwidth=80, anchor="center", stretch=True)
        self.table.tag_configure("township", background=c["surface_alt"])
        self.table.tag_configure("station", background=c["surface"], foreground=c["muted"])
        self.table.tag_configure("total", background=c["background"])
        self._scale_table(1.0)
        self.table.pack(fill="x", padx=16, pady=(0, 16))
        self.table.bind("<<TreeviewSelect>>", self._table_selected)

    def _scale_table(self, zoom: float):
        f = self.family
        style = ttk.Style(self)
        style.configure("Dash.Treeview", rowheight=round(34 * zoom), font=(f, max(6, round(11 * zoom))))
        style.configure("Dash.Treeview.Heading", font=(f, max(6, round(11 * zoom)), "bold"))
        self.table.tag_configure("township", font=(f, max(6, round(11 * zoom)), "bold"))
        self.table.tag_configure("total", font=(f, max(6, round(11 * zoom)), "bold"))
        self.table.column("#0", width=round(260 * zoom))

    def redraw_all(self):
        """Redraw every chart in its final state (no animation)."""
        for card in self._chart_cards:
            card.progress = 1.0
            card.redraw()

    def set_zoom(self, zoom: float):
        self._zoom = zoom
        for card in self._chart_cards:
            card.set_zoom(zoom)
        self._scale_table(zoom)

    # data ----------------------------------------------------------------------
    def refresh(self):
        try:
            self.data = prepare_voters(self.get_dataset())
        except Exception:
            self.data = pd.DataFrame(columns=["township", "station", "voted", "criminal", "gender", "age", "age_group"])
        townships = sorted(self.data["township"].unique().tolist()) if not self.data.empty else []
        self.township_menu.configure(values=[ALL_TOWNSHIPS] + townships)
        if self.selected not in townships:
            self.selected = ALL_TOWNSHIPS
        self.township_menu.set(self.selected)
        self.meta_label.configure(
            text=f"ဒေတာဖိုင်: {self.get_source_name()}   •   မှတ်တမ်း {mm_number(len(self.data))}   •   "
                 f"တွက်ချက်ချိန် {datetime.now().strftime('%H:%M:%S').translate(_TO_MM)}"
        )
        # Opening the page / pressing refresh plays the full intro animation (after one paint of the layout).
        self._render(intro=True)

    def _select_township(self, township: str):
        self.selected = ALL_TOWNSHIPS if township == self.selected and township != ALL_TOWNSHIPS else township
        self.township_menu.set(self.selected)
        self._render(intro=False)

    def _table_selected(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        item = selection[0]
        parent = self.table.parent(item)
        township = self.table.item(parent or item, "text")
        if township in self.data["township"].values and township != self.selected:
            self._select_township(township)

    def _filtered(self) -> pd.DataFrame:
        if self.selected == ALL_TOWNSHIPS:
            return self.data
        return self.data[self.data["township"] == self.selected]

    def _township_rows(self) -> List[Dict[str, Any]]:
        if self.data.empty:
            return []
        grouped = self.data.groupby("township").agg(total=("voted", "size"), voted=("voted", "sum"), criminal=("criminal", "sum"))
        rows = [{"name": name, "total": int(r.total), "voted": int(r.voted), "pending": int(r.total - r.voted),
                 "criminal": int(r.criminal)} for name, r in grouped.iterrows()]
        return sorted(rows, key=lambda r: r["voted"] / r["total"] if r["total"] else 0, reverse=True)

    def _render(self, intro: bool = False):
        """intro=True: everything grows from zero; intro=False (filter change): KPIs count from their
        current values, the filtered charts replay quickly and the township chart just re-highlights."""
        intro_ms = ANIMATION_MS if intro else 0
        filter_ms = ANIMATION_MS if intro else FILTER_ANIMATION_MS
        delay = INTRO_DELAY_MS if intro else 0
        data = self._filtered()
        total = len(data)
        voted = int(data["voted"].sum()) if total else 0
        pending = total - voted
        scope = "" if self.selected == ALL_TOWNSHIPS else f" • {self.selected}"
        kpi = dict(duration=filter_ms, from_zero=intro, delay=delay)
        self.kpis["total"].count_to(total, f"မြို့နယ် {mm_number(data['township'].nunique() if total else 0)} ခု{scope}", **kpi)
        self.kpis["voted"].count_to(voted, f"{mm_percent(voted, total)} မဲပေးပြီး", **kpi)
        self.kpis["pending"].count_to(pending, f"{mm_percent(pending, total)} ကျန်ရှိ", **kpi)
        if self.is_admin:
            criminal = int(data["criminal"].sum()) if total else 0
            self.kpis["criminal"].count_to(criminal, f"မဲဆန္ဒရှင်၏ {mm_percent(criminal, total)}", **kpi)
        else:
            stations = data[["township", "station"]].drop_duplicates().shape[0] if total else 0
            self.kpis["stations"].count_to(stations, "မြို့နယ်အလိုက် မဲရုံများ", **kpi)

        township_rows = self._township_rows()
        self.township_chart.render(lambda card, w, h: draw_stacked_hbars(card, w, h, township_rows, self.selected, self._select_township), intro_ms, delay)
        self.donut_chart.subtitle.configure(text=self.selected)
        self.donut_chart.render(lambda card, w, h: draw_donut(card, w, h, voted, pending), filter_ms, delay)

        age_groups = []
        for label, _low, _high in AGE_GROUPS:
            part = data[data["age_group"] == label]
            age_groups.append((label, int(part["voted"].sum()), int(len(part) - part["voted"].sum())))
        self.age_chart.render(lambda card, w, h: draw_grouped_vbars(card, w, h, age_groups), filter_ms, delay)

        genders = []
        for label in ("အမျိုးသား", "အမျိုးသမီး"):
            part = data[data["gender"] == label]
            genders.append((label, int(part["voted"].sum()), int(len(part) - part["voted"].sum())))
        self.gender_chart.render(lambda card, w, h: draw_grouped_vbars(card, w, h, genders), filter_ms, delay)

        if self.criminal_chart is not None:
            crim_rows = sorted(((r["name"], r["criminal"], r["total"]) for r in township_rows), key=lambda r: r[1], reverse=True)
            self.criminal_chart.render(lambda card, w, h: draw_simple_hbars(card, w, h, crim_rows, DANGER_COLOR, self.selected), intro_ms, delay)

        bins = []
        ages = data["age"].dropna()
        if not ages.empty:
            start = 18
            while start <= max(85, int(ages.max())):
                end = start + 4 if start > 18 else 24
                part = data[(data["age"] >= start) & (data["age"] <= end)]
                label = f"{start}–{end}".translate(_TO_MM)
                bins.append((label, int(part["voted"].sum()), int(len(part) - part["voted"].sum())))
                start = end + 1
        self.histogram_chart.render(lambda card, w, h: draw_stacked_vbars(card, w, h, bins), filter_ms, delay)
        self._fill_table(township_rows)

    def _fill_table(self, township_rows: List[Dict[str, Any]]):
        table = self.table
        table.delete(*table.get_children())

        def values(total: int, voted: int, criminal: int) -> List[str]:
            row = [mm_number(total), mm_number(voted), mm_number(total - voted), mm_percent(voted, total)]
            return row + ([mm_number(criminal)] if self.is_admin else [])

        selected_item = None
        for row in township_rows:
            item = table.insert("", "end", text=row["name"], values=values(row["total"], row["voted"], row["criminal"]),
                                tags=("township",), open=row["name"] == self.selected)
            if row["name"] == self.selected:
                selected_item = item
            stations = self.data[self.data["township"] == row["name"]].groupby("station").agg(
                total=("voted", "size"), voted=("voted", "sum"), criminal=("criminal", "sum"))
            for station, s in sorted(stations.iterrows(), key=lambda pair: _to_int(pair[0]) or 0):
                table.insert(item, "end", text=f"    {station}", values=values(int(s.total), int(s.voted), int(s.criminal)), tags=("station",))
        if township_rows:
            total = sum(r["total"] for r in township_rows)
            table.insert("", "end", text="စုစုပေါင်း", tags=("total",),
                         values=values(total, sum(r["voted"] for r in township_rows), sum(r["criminal"] for r in township_rows)))
        table.configure(height=min(14, max(5, len(table.get_children()) + (len(table.get_children(selected_item)) if selected_item else 0))))
        if selected_item:
            table.selection_set(selected_item)
            table.see(selected_item)

    def _export_summary(self):
        rows = self._township_rows()
        if not rows:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="voter_summary.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        frame = pd.DataFrame([{
            "မြို့နယ်": r["name"], "စုစုပေါင်း": r["total"], "မဲပေးပြီး": r["voted"], "မဲမပေးရသေး": r["pending"],
            "မဲပေးမှုနှုန်း(%)": round(r["voted"] / r["total"] * 100, 1) if r["total"] else 0,
            **({"ပြစ်မှုရှိ": r["criminal"]} if self.is_admin else {}),
        } for r in rows])
        frame.to_csv(path, index=False, encoding="utf-8-sig")

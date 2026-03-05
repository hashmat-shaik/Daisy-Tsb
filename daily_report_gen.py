"""
daily_report_gen.py
Generates a single stats image containing:
  - Left half:  Pie chart of study time broken down by tag
  - Right half: Bar chart of study hours over the last 7 days

Designed to be run in a thread executor (no async).
Returns a BytesIO PNG buffer.
"""

import io
import math
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure          # OOP only — no pyplot globals, thread-safe
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker

# ── Colour palette (Discord dark theme friendly) ──────────────────────────────
BG_COLOR       = "#1E1F22"       # Discord dark background
CARD_COLOR     = "#2B2D31"       # Slightly lighter card surface
ACCENT_ORANGE  = "#F0A500"       # Gold/orange — matches the embed accent
TEXT_PRIMARY   = "#FFFFFF"
TEXT_SECONDARY = "#B5BAC1"       # Discord muted text colour
GRID_COLOR     = "#3A3C42"

# Tag slice colours — cycling palette
TAG_COLORS = [
    "#F0A500", "#5865F2", "#57F287", "#EB459E",
    "#FEE75C", "#ED4245", "#00B0F4", "#FF7043",
    "#AB47BC", "#26C6DA",
]

NO_DATA_COLOR = "#3A3C42"

# ── Canvas dimensions ─────────────────────────────────────────────────────────
FIG_W   = 10      # inches
FIG_H   = 4.5     # inches
DPI     = 120


def _format_hours(seconds: float) -> str:
    """Convert seconds to a readable string like '2h 30m'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h == 0:
        return f"{m}m"
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def _short_date(date_str: str) -> str:
    """'2025-03-15' → 'Mar 15'"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%b %d")
    except Exception:
        return date_str


def generate_stats_image(
    tag_times: list[tuple[str, float]],       # [(tag, seconds), ...]
    daily_history: list[tuple[str, float]],   # [(YYYY-MM-DD, seconds), ...] len=7
    daily_secs: float = None,                 # today's total seconds — used for centre label
) -> io.BytesIO:
    """
    Renders the stats card and returns a BytesIO PNG buffer.
    Both arguments may be empty/zeroed — the chart degrades gracefully.
    """

    fig = Figure(figsize=(FIG_W, FIG_H), facecolor=BG_COLOR)
    FigureCanvasAgg(fig)  # attach a non-interactive canvas — required for savefig without pyplot

    # Two equal columns
    ax_pie = fig.add_axes([0.03, 0.08, 0.42, 0.84])   # left
    ax_bar = fig.add_axes([0.56, 0.12, 0.42, 0.78])   # right

    # ── GLOBAL STYLE ─────────────────────────────────────────────────────────
    for ax in (ax_pie, ax_bar):
        ax.set_facecolor(CARD_COLOR)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)

    # ═════════════════════════════════════════════════════════════════════════
    #  LEFT — PIE CHART
    # ═════════════════════════════════════════════════════════════════════════
    ax_pie.set_aspect("equal")

    # Filter to tags that actually have time
    active_tags = [(t, s) for t, s in tag_times if s > 0]

    if not active_tags:
        # Empty state — single grey slice with label
        ax_pie.pie(
            [1],
            colors=[NO_DATA_COLOR],
            startangle=90,
            wedgeprops={"linewidth": 2, "edgecolor": BG_COLOR},
        )
        ax_pie.text(
            0, 0, "No tag\ndata yet",
            ha="center", va="center",
            fontsize=11, color=TEXT_SECONDARY,
            fontweight="bold"
        )
    else:
        sizes  = [s for _, s in active_tags]
        labels = [t for t, _ in active_tags]
        colors = [TAG_COLORS[i % len(TAG_COLORS)] for i in range(len(active_tags))]

        total = sum(sizes)

        # FIX B10: use daily_secs if provided — tag_times is all-time, not just today
        center_secs = daily_secs if daily_secs is not None else total

        wedges, _ = ax_pie.pie(
            sizes,
            colors=colors,
            startangle=90,
            wedgeprops={"linewidth": 2.5, "edgecolor": BG_COLOR},
            pctdistance=0.78,
        )

        # Centre label — daily time  # FIX B10
        ax_pie.text(
            0, 0.06, _format_hours(center_secs),
            ha="center", va="center",
            fontsize=15, color=TEXT_PRIMARY, fontweight="bold"
        )
        ax_pie.text(
            0, -0.18, "total today",
            ha="center", va="center",
            fontsize=9, color=TEXT_SECONDARY
        )

        # Donut effect
        centre_circle = mpatches.Circle((0, 0), 0.55, color=CARD_COLOR)
        ax_pie.add_artist(centre_circle)

        # Legend below the pie
        legend_patches = [
            mpatches.Patch(color=colors[i], label=f"{labels[i]}  {_format_hours(sizes[i])}")
            for i in range(len(active_tags))
        ]
        ax_pie.legend(
            handles=legend_patches,
            loc="lower center",
            bbox_to_anchor=(0.5, -0.22),
            ncol=min(3, len(active_tags)),
            frameon=False,
            fontsize=8.5,
            labelcolor=TEXT_PRIMARY,
        )

    ax_pie.set_title("Today by Subject", color=TEXT_PRIMARY, fontsize=12,
                     fontweight="bold", pad=10)

    # ═════════════════════════════════════════════════════════════════════════
    #  RIGHT — BAR CHART  (7 days)
    # ═════════════════════════════════════════════════════════════════════════
    dates   = [_short_date(d) for d, _ in daily_history]
    seconds = [s for _, s in daily_history]
    hours   = [s / 3600 for s in seconds]

    # Highlight today (last bar)
    bar_colors = [TEXT_SECONDARY] * 6 + [ACCENT_ORANGE]

    bars = ax_bar.bar(
        range(7), hours,
        color=bar_colors,
        width=0.6,
        zorder=3,
        linewidth=0,
    )

    # Value labels on top of each bar
    for bar, h in zip(bars, hours):
        if h > 0:
            ax_bar.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.05,
                _format_hours(h * 3600),
                ha="center", va="bottom",
                fontsize=7.5, color=TEXT_PRIMARY, fontweight="bold"
            )

    # Axes styling
    ax_bar.set_xticks(range(7))
    ax_bar.set_xticklabels(dates, color=TEXT_SECONDARY, fontsize=8.5)
    ax_bar.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:.0f}h"))
    ax_bar.tick_params(colors=TEXT_SECONDARY, which="both")
    ax_bar.yaxis.label.set_color(TEXT_SECONDARY)
    ax_bar.set_facecolor(CARD_COLOR)
    ax_bar.yaxis.set_tick_params(labelcolor=TEXT_SECONDARY)
    ax_bar.grid(axis="y", color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax_bar.set_axisbelow(True)

    # Remove top/right spines
    ax_bar.spines["top"].set_visible(False)
    ax_bar.spines["right"].set_visible(False)
    ax_bar.spines["left"].set_color(GRID_COLOR)
    ax_bar.spines["bottom"].set_color(GRID_COLOR)

    ax_bar.set_title("Last 7 Days", color=TEXT_PRIMARY, fontsize=12,
                     fontweight="bold", pad=10)

    # ── Save ─────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor=BG_COLOR, dpi=DPI)
    # No plt.close() needed — Figure is not registered with pyplot's global state
    buf.seek(0)
    return buf

"""Hand-written SVG charts for the report: horizontal bars with intervals, and a heatmap.

Label widths come from Helvetica's average advance per character class, which is close enough
to lay out a figure without a font engine.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"
INK, SOFT, MUTED = "#1f2430", "#4b5260", "#868b94"
GRID, AXIS, GAP_BAR = "#e6e4de", "#c3c1b8", "#cfccc4"
RED, BLUE = "#c8102e", "#3d6fb6"  # the attack condition; the control or mitigated condition
SIZE_COLORS = ("#f08a7f", "#a8101f")  # two steps of one red ramp, the larger model darker
HEAT = ("#f5e4e1", "#f4b3aa", "#e4675c", "#c01f2a", "#8a0b18")
HALF, FULL, PAD = 360, 720, 12  # half- and full-width figures print at the same type scale
NOTE_SIZE, NOTE_LEADING = 10, 13.5
SIN45 = 0.71  # a label turned by 45 degrees spans this share of its length on each axis
GAP_BAND = 30  # height of a gap bar at 100 points


def text_width(s, size):
    return size * sum(0.28 if c in "fijlrt.,:;'()| " else 0.84 if c in "mwMW%"
                      else 0.67 if c.isupper() else 0.56 for c in s)


def signed_points(delta):
    points = round(100 * delta)
    return f"{points:+d}".replace("-", "\N{MINUS SIGN}") if points else "0"


def count_label(values, noun):
    low, high = min(values), max(values)
    return f"n = {low} {noun}" if low == high else f"n = {low}–{high} {noun}"


def text(x, y, s, size=11, fill=INK, anchor="start", attrs=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}"{attrs}>{escape(str(s))}</text>')


def document(width, height, title, parts):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" '
            f'width="{width}" height="{height:.0f}" role="img" aria-labelledby="title" '
            f'font-family="{FONT}">\n<title id="title">{escape(title)}</title>\n'
            '<rect width="100%" height="100%" fill="#ffffff"/>\n' + "\n".join(parts) + "\n</svg>\n")


def bar(x, y, width, height, fill, tip):
    r = min(2.0, width, height / 2)  # square at the baseline, rounded at the data end
    d = (f"M{x:.1f},{y:.1f}h{width - r:.1f}a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f}"
         f"v{height - 2 * r:.1f}a{r:.1f},{r:.1f} 0 0 1 {-r:.1f},{r:.1f}h{r - width:.1f}z")
    return f'<path d="{d}" fill="{fill}"><title>{escape(tip)}</title></path>'


def whisker(x0, x1, y, cap):
    return (f'<path d="M{x0:.1f},{y:.1f}H{x1:.1f}M{x0:.1f},{y - cap:.1f}V{y + cap:.1f}'
            f'M{x1:.1f},{y - cap:.1f}V{y + cap:.1f}" stroke="{SOFT}" fill="none"/>')


def legend(series, y, with_ci):
    parts, x = [], PAD
    for name, color in series:
        parts += [f'<rect x="{x:.1f}" y="{y - 8.5:.1f}" width="9" height="9" rx="2" '
                  f'fill="{color}"/>', text(x + 13, y, name, 10.5, SOFT)]
        x += 13 + text_width(name, 10.5) + 14
    if with_ci:
        parts += [whisker(x, x + 14, y - 4, 3), text(x + 19, y, "95% CI", 10.5, SOFT)]
    return parts


def wrap(sentence, width, size):
    lines = [""]
    for word in sentence.split():
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and text_width(trial, size) > width:
            lines.append(word)
        else:
            lines[-1] = trial
    return lines


def note(sentence, top, width):
    """The note's lines below top, and the y where the last one ends."""
    lines = wrap(sentence, width - 2 * PAD, NOTE_SIZE)
    baselines = [top + NOTE_LEADING * (k + 1) for k in range(len(lines))]
    parts = [text(PAD, y, line, NOTE_SIZE, SOFT) for y, line in zip(baselines, lines)]
    return parts, baselines[-1] + 4  # room for descenders


def bar_chart(rows, series, sentence, title, right_header=None, total=False):
    """Horizontal bars, one group per row and one bar per series, whiskers where a CI is known.

    rows are (label, [entry per series], right-column text or None); an entry has "rate" and
    optionally "ci95". Rows without right-column text carry each bar's value instead. With total,
    the last row is set apart as the pooled row.
    """
    size, bar_h, gap = (10, 4.5, 5.0) if len(rows) > 12 else (11, 9.0, 9.0)
    x0 = PAD + max(text_width(label, size) for label, _, _ in rows) + 8
    plot_w = HALF - x0 - PAD - 32
    at = lambda rate: x0 + rate * plot_w  # noqa: E731
    group_h = len(series) * (bar_h + 1.5) - 1.5
    top = PAD + 28
    row_y = [top + i * (group_h + gap) + (gap if total and i == len(rows) - 1 else 0)
             for i in range(len(rows))]
    bottom = row_y[-1] + group_h
    parts = legend(series, PAD + 9, any(e.get("ci95") for _, entries, _ in rows for e in entries))
    for q in (0, .25, .5, .75, 1):
        line = AXIS if q == 0 else GRID
        parts += [f'<path d="M{at(q):.1f},{top - 5}V{bottom + 5}" stroke="{line}"/>',
                  text(at(q), bottom + 17, f"{q:.0%}", 10, MUTED, "middle")]
    if total:
        parts.append(f'<path d="M{PAD},{row_y[-1] - gap:.1f}H{HALF - PAD}" stroke="{AXIS}"/>')
    if right_header:
        parts.append(text(HALF - PAD, top - 9, right_header, 10, MUTED, "end"))
    for i, (y, (label, entries, right)) in enumerate(zip(row_y, rows)):
        middle = y + group_h / 2 + size * 0.35
        bold = ' font-weight="600"' if total and i == len(rows) - 1 else ""
        parts.append(text(x0 - 8, middle, label, size, INK, "end", bold))
        for j, ((name, color), e) in enumerate(zip(series, entries)):
            by, value_x = y + j * (bar_h + 1.5), at(e["rate"])
            parts.append(bar(x0, by, e["rate"] * plot_w, bar_h, color,
                             f"{label}, {name}: {e['rate']:.0%}"))
            if e.get("ci95"):
                low, high = e["ci95"]
                parts.append(whisker(at(low), at(high), by + bar_h / 2, bar_h / 2 + 1))
                value_x = at(high)  # the value goes past the whisker, not across it
            if right is None:
                parts.append(text(value_x + 4, by + bar_h / 2 + 3.5, f"{e['rate']:.0%}", 10, SOFT))
        if right is not None:
            parts.append(text(HALF - PAD, middle, right, size, SOFT, "end"))
    lines, end = note(sentence, bottom + 22.5, HALF)
    return document(HALF, end + PAD, title, parts + lines)


def heat(rate):
    pos = rate * (len(HEAT) - 1)
    i = min(int(pos), len(HEAT) - 2)
    lo, hi = bytes.fromhex(HEAT[i][1:]), bytes.fromhex(HEAT[i + 1][1:])
    return "#" + "".join(f"{round(a + (b - a) * (pos - i)):02x}" for a, b in zip(lo, hi))


def heat_legend(rows):
    sizes = {c["n"] for r in rows for c in r["per_lang"].values()}
    if len(sizes) == 1:
        n = sizes.pop()
        stops, caption = [(k / n, str(k)) for k in range(n + 1)], f"Wrong answers of {n}"
    else:
        stops, caption = [(q, f"{q:.0%}") for q in (0, .25, .5, .75, 1)], "Share wrong"
    x = FULL - PAD - 30 * len(stops)
    parts = [text(PAD, PAD + 10, "Gap: highest minus lowest language rate, in points", 10.5, SOFT),
             text(x - 8, PAD + 10, caption, 10.5, SOFT, "end")]
    for i, (rate, label) in enumerate(stops):
        parts += [f'<rect x="{x + 30 * i}" y="{PAD}" width="13" height="12" rx="1.5" '
                  f'fill="{heat(rate)}"/>', text(x + 30 * i + 17, PAD + 10, label, 10.5, SOFT)]
    return parts


def gap_axis(left, base):
    return [f'<path d="M{left:.1f},{base - GAP_BAND}H{FULL - PAD}" stroke="{GRID}"/>',
            f'<path d="M{left:.1f},{base}H{FULL - PAD}" stroke="{AXIS}"/>',
            text(left - 8, base - GAP_BAND + 3.5, "100", 9, MUTED, "end"),
            text(left - 8, base - GAP_BAND / 2 + 4, "Gap", 11, INK, "end"),
            text(left - 8, base + 3.5, "0", 9, MUTED, "end")]


def heatmap(rows, columns, sentence, title):
    """Hypotheses as columns in the caller's order, languages as rows, the gap as a bar on top.
    Each row has a "label"; rows that are not "reproduced" get a grey one."""
    longest = max(text_width(r["label"], 10) for r in rows)
    left = PAD + max(max(text_width(name, 11) for name in columns.values()) + 8, SIN45 * longest)
    col, cell = (FULL - left - PAD) / len(rows), 17
    base = PAD + 28 + GAP_BAND
    top = base + 8
    bottom = top + len(columns) * (cell + 2) - 2
    parts = heat_legend(rows) + gap_axis(left, base)
    parts += [text(left - 8, top + j * (cell + 2) + cell / 2 + 4, name, 11, INK, "end")
              for j, name in enumerate(columns.values())]
    for i, r in enumerate(rows):
        x, h = left + i * col + 1, r["gap"] * GAP_BAND
        parts.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{col - 2:.1f}" '
                     f'height="{h:.1f}" fill="{GAP_BAR}"><title>gap {r["gap"]:.0%}</title></rect>')
        for j, lang in enumerate(columns):
            c = r["per_lang"][lang]
            parts.append(f'<rect x="{x:.1f}" y="{top + j * (cell + 2)}" width="{col - 2:.1f}" '
                         f'height="{cell}" rx="1.5" fill="{heat(c["rate"])}"><title>'
                         f'{escape(r["label"])}, {columns[lang]}: {c["k"]} of {c["n"]}'
                         '</title></rect>')
        cx, cy = x + col / 2 + 2, bottom + 9
        parts.append(text(cx, cy, r["label"], 10, INK if r["reproduced"] else MUTED, "end",
                          f' transform="rotate(-45 {cx:.1f} {cy:.1f})"'))
    lines, end = note(sentence, bottom + 9 + SIN45 * longest, FULL)
    return document(FULL, end + PAD, title, parts + lines)

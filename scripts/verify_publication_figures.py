"""Check the published figures against the article that prints them.

Four properties are checked, and each exists because a figure can fail it silently.

Which file is which. The figure files are named for the order in which they were written,
not for the order the article prints them, so a reader who wants the script behind Figure 6
cannot get there from the file name. The table below is that mapping, and every entry is
resolved, so a renamed or missing figure fails here instead of leaving a reader guessing.

Resolution. Every figure needs a 600 dpi raster and a vector counterpart: the raster is what
the Word document carries, the vector is what survives typesetting.

Legibility in print. Three of these figures are drawn on a 7.1 inch canvas and printed at
14 cm, so their text is reduced by about a fifth on the way to the page. What matters is the
size on paper, so the sizes are read from the SVG and scaled by that reduction before being
compared against a floor. The measured minimum is printed for every figure rather than only
the verdict, because "6.4 pt" tells an author something that "passed" does not.

Greyscale. Colour is the first thing a photocopy loses, and the categorical palette of
Figure 4 does not survive it: its five method colours span 0.002 in relative luminance,
which is no separation at all. The figure stays readable because every method also carries
its own marker shape, and that is what is checked -- markers pairwise distinct -- with the
luminance spread reported so the reliance on shape is visible rather than assumed. The
sequential scales are a different matter: cividis and viridis are perceptually uniform and
colour-blind-safe by construction, so what needs checking is only that no heatmap quietly
moves to a scale that is not.

Run:  python scripts/verify_publication_figures.py
Exit code 0 when every figure passes.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / "results" / "figures"
BENCHMARK_DIR = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark"

# The canvas the figures are drawn on. Both producing scripts author at this width and let
# the journal reduce, which is why the printed width below is what legibility is judged on.
CANVAS_CM = 7.1 * 2.54

# article figure -> (file stem without extension, printed width in cm, what it shows)
FIGURES: dict[str, tuple[Path, float, str]] = {
    "Figure 1": (
        BENCHMARK_DIR / "little_bear_river_2025_benchmark_map",
        CANVAS_CM,
        "benchmark network over its service areas",
    ),
    "Figure 2": (
        FIGURE_DIR / "Figure_2_cti_rlex_solution_workflow",
        CANVAS_CM,
        "solution workflow",
    ),
    "Figure 3": (
        FIGURE_DIR / "Figure_1_claimant_guarantees",
        14.0,
        "claimant-level effect of bounded recourse",
    ),
    "Figure 4": (
        FIGURE_DIR / "Figure_6_method_tradeoff_two_panel",
        14.0,
        "delivery-fairness trade-off and lexicographic discrimination",
    ),
    "Figure 5": (
        FIGURE_DIR / "Figure_2_recourse_frontier",
        CANVAS_CM,
        "recourse frontier and normalized effort",
    ),
    "Figure 6": (
        FIGURE_DIR / "Figure_3_period_service_heatmap",
        CANVAS_CM,
        "scenario-period delivered-demand ratios",
    ),
    "Figure 7": (
        FIGURE_DIR / "Figure_4_source_activation_water_balance",
        CANVAS_CM,
        "seasonal source activation and water balance",
    ),
    "Figure 8": (
        FIGURE_DIR / "Figure_5_sensitivity_heatmaps",
        14.0,
        "factor interactions at recourse-budget scale 1.0",
    ),
}

# Written by create_results_artifacts.py and superseded by the two-panel Figure 4. It is
# kept so the single-panel form stays reproducible, and named here so a reader who finds it
# in the directory knows the article does not print it.
UNUSED = FIGURE_DIR / "Figure_6_method_tradeoff"

# Figure 2 is a drawn schematic of the solution workflow, not a plot of any result. No
# script regenerates it and none should: the SVG shipped beside the PNG is its editable
# source. Naming it here keeps a reader from hunting for a producer that does not exist,
# and keeps the rest of the mapping honest -- every other figure in the article comes from
# a file in results/. It is still checked for resolution and printed type size, because it
# is printed at the same size as the others.
SCHEMATICS = frozenset({"Figure 2"})

MINIMUM_PRINTED_POINTS = 7.0   # labels, annotations and tick text
MINIMUM_SCRIPT_POINTS = 5.0    # subscripts and superscripts, set at 0.7 of their base
SAFE_SEQUENTIAL_SCALES = {"cividis", "viridis", "magma", "inferno", "plasma", "gray"}

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"  FAIL  {message}")


def relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance, which is what a greyscale print reduces a colour to."""

    raw = hex_colour.lstrip("#")
    channels = [int(raw[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def printed_minimum_points(svg: Path, printed_cm: float) -> tuple[float, float] | None:
    """The smallest body type and the smallest type of any kind, in points on paper.

    The two are separated because matplotlib sets a subscript at 0.7 of its base size, and a
    6.3 pt subscript under a 9 pt label is ordinary typography rather than a figure with
    unreadable text. Measuring the raw minimum reports the subscript and hides the label, so
    a size that is 0.7 of another size present in the same figure is classified as script.
    """

    body = svg.read_text(encoding="utf-8")
    sizes = sorted({float(value) for value in re.findall(r"font-size:\s*([0-9.]+)px", body)})
    if not sizes:
        return None
    scripts = {
        size
        for size in sizes
        if any(abs(size - 0.7 * base) < 0.05 for base in sizes if base > size)
    }
    ordinary = [size for size in sizes if size not in scripts] or sizes
    scale = printed_cm / CANVAS_CM
    return min(ordinary) * scale, min(sizes) * scale


def check_files() -> None:
    print("Figure files, resolution and printed type size")
    for number, (stem, printed_cm, subject) in FIGURES.items():
        png, svg = stem.with_suffix(".png"), stem.with_suffix(".svg")
        if not png.exists():
            fail(f"{number}: missing {png.relative_to(ROOT)}")
            continue
        if not svg.exists() or svg.stat().st_size == 0:
            fail(f"{number}: missing or empty {svg.relative_to(ROOT)}")
            continue
        with Image.open(png) as image:
            dpi = image.info.get("dpi")
            width, height = image.size
        if dpi is None or min(dpi) < 599.0:
            fail(f"{number}: expected 600 dpi metadata in {png.name}, found {dpi}")
            continue
        measured = printed_minimum_points(svg, printed_cm)
        if measured is None:
            note = "no text"
        else:
            ordinary, any_size = measured
            if ordinary < MINIMUM_PRINTED_POINTS:
                fail(
                    f"{number}: smallest printed label is {ordinary:.1f} pt at "
                    f"{printed_cm:.1f} cm, below the {MINIMUM_PRINTED_POINTS:.1f} pt floor"
                )
                continue
            if any_size < MINIMUM_SCRIPT_POINTS:
                fail(
                    f"{number}: a subscript prints at {any_size:.1f} pt, below the "
                    f"{MINIMUM_SCRIPT_POINTS:.1f} pt floor"
                )
                continue
            note = f"labels from {ordinary:.1f} pt at {printed_cm:.1f} cm"
            if any_size < ordinary - 0.05:
                note += f", subscripts {any_size:.1f} pt"
        print(f"  ok    {number}: {png.name}, {width}x{height} px, {note} - {subject}")
        if number in SCHEMATICS:
            print("        drawn schematic, shipped as an asset; the SVG is its source")

    if UNUSED.with_suffix(".png").exists():
        print(f"  note  {UNUSED.name} is produced but not printed by the article")


def declared_styles(source: Path, table: str) -> dict[str, tuple[str, str]]:
    """Read a ``name: (marker, colour)`` table out of a producing script."""

    text = source.read_text(encoding="utf-8")
    block = re.search(rf"^{table} = \{{(.*?)^\}}", text, re.DOTALL | re.MULTILINE)
    if block is None:
        raise SystemExit(f"{source.name}: no {table} table to read")
    return {
        name: (marker, colour)
        for name, marker, colour in re.findall(
            r'"([^"]+)":\s*\("([^"]*)",\s*"(#[0-9A-Fa-f]{6})"\)', block.group(1)
        )
    }


def declared_palette(source: Path, table: str) -> list[str]:
    """Read the hex colours of a ``key: "#rrggbb"`` table out of a producing script."""

    text = source.read_text(encoding="utf-8")
    block = re.search(rf"^{table} = \{{(.*?)^\}}", text, re.DOTALL | re.MULTILINE)
    if block is None:
        raise SystemExit(f"{source.name}: no {table} table to read")
    return re.findall(r'"(#[0-9A-Fa-f]{6})"', block.group(1))


def closest_pair(colours: list[str]) -> float:
    luminances = [relative_luminance(colour) for colour in colours]
    return min(abs(first - second) for first, second in itertools.combinations(luminances, 2))


def check_greyscale() -> None:
    """Report what survives a greyscale print, and fail only where nothing would.

    None of these palettes separates well in grey, and saying so is more useful than a
    threshold that would either pass everything or condemn a figure that is in fact
    readable. What makes each one readable is named beside its measurement; the one
    property that is enforced is the one Figure 4 depends on, that no two methods share a
    marker, because if they did the figure would lose its distinction entirely.
    """

    print("\nGreyscale separation of the categorical palettes")
    styles = declared_styles(ROOT / "scripts" / "update_figure4_two_panel.py", "STYLES")
    if len(styles) < 2:
        fail("Figure 4: no method styles could be read")
        return
    markers = [marker for marker, _ in styles.values()]
    if len(set(markers)) != len(markers):
        fail(f"Figure 4: two methods share a marker, {sorted(markers)}")
        return
    spread = closest_pair([colour for _, colour in styles.values()])
    print(
        f"  ok    Figure 4: {len(styles)} methods, {len(set(markers))} distinct markers; "
        f"closest colours differ by {spread:.3f} in luminance, so shape carries the "
        "difference"
    )

    artifacts = ROOT / "scripts" / "create_results_artifacts.py"
    for label, source, table, cue in (
        (
            "Figure 1",
            BENCHMARK_DIR / "plot_benchmark_map.py",
            "COMPANY_COLORS",
            "every source and terminal is labelled on the map",
        ),
        (
            "Figure 7(a)",
            artifacts,
            "SOURCE_COLORS",
            "the stack keeps one order and its segments are separated by white rules",
        ),
    ):
        colours = declared_palette(source, table)
        if len(colours) < 2:
            fail(f"{label}: fewer than two colours in {table}")
            continue
        print(
            f"  ok    {label}: {len(colours)} categories, closest colours differ by "
            f"{closest_pair(colours):.3f} in luminance; {cue}"
        )


def check_colour_scales() -> None:
    print("\nSequential colour scales")
    source = (ROOT / "scripts" / "create_results_artifacts.py").read_text(encoding="utf-8")
    scales = sorted(set(re.findall(r'cmap="([^"]+)"', source)))
    if not scales:
        fail("no colour scale is declared in create_results_artifacts.py")
        return
    unsafe = [scale for scale in scales if scale.rstrip("_r") not in SAFE_SEQUENTIAL_SCALES]
    if unsafe:
        fail(f"colour scales that are not perceptually uniform: {unsafe}")
        return
    print(f"  ok    every heatmap uses a perceptually uniform scale: {', '.join(scales)}")


def main() -> None:
    check_files()
    check_greyscale()
    check_colour_scales()
    print()
    if failures:
        print(f"{len(failures)} figure problem(s) found")
        sys.exit(1)
    print(f"{len(FIGURES)} figures checked, no problems found")


if __name__ == "__main__":
    main()

"""Verify that publication figures have 600 dpi PNG and SVG counterparts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PNG_FILES = sorted((ROOT / "results" / "figures").glob("Figure_*.png")) + [
    ROOT
    / "DATA"
    / "LittleBearRiver_2025_Benchmark"
    / "little_bear_river_2025_benchmark_map.png"
]


def main() -> None:
    if not PNG_FILES:
        raise RuntimeError("No publication PNG figures were found")
    for png in PNG_FILES:
        svg = png.with_suffix(".svg")
        if not svg.exists() or svg.stat().st_size == 0:
            raise AssertionError(f"Missing or empty SVG counterpart: {svg}")
        with Image.open(png) as image:
            dpi = image.info.get("dpi")
            if dpi is None or min(dpi) < 599.0:
                raise AssertionError(f"{png}: expected 600 dpi metadata, found {dpi}")
            width, height = image.size
        print(
            f"PASS {png.relative_to(ROOT)}: {width}x{height} px, "
            f"{dpi[0]:.1f}x{dpi[1]:.1f} dpi, SVG retained"
        )


if __name__ == "__main__":
    main()

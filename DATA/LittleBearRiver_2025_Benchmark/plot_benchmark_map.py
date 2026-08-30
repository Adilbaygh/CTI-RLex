"""Render the Little Bear River benchmark graph over its service areas."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BENCHMARK = HERE / "benchmark.json"
# The open layers are resolved exactly as generate_benchmark.py resolves them. They are
# not part of the repository, and the directory this used to assume does not exist, so a
# reader following the benchmark README could not redraw this map at all.
DATASETS = Path(os.environ.get("LEXIMIN_DATASETS", str(REPO / "DataSETs")))
SERVICE_AREAS = (
    DATASETS / "Utah Irrigation Company Service Areas" / "utah_service_areas.geojson"
)
SUBAREAS = DATASETS / "Utah Water Budget Subareas" / "utah_subareas.geojson"

PNG_OUTPUT = HERE / "little_bear_river_2025_benchmark_map.png"
SVG_OUTPUT = HERE / "little_bear_river_2025_benchmark_map.svg"

COMPANY_COLORS = {
    88: "#E69F00",
    130: "#009E73",
    132: "#CC79A7",
}
COMPANY_LABELS = {
    88: "Hyrum service area",
    130: "Paradise service area",
    132: "Porcupine Highline service area",
}
TERMINAL_LABELS = {
    "n_16801": "Hyrum terminal",
    "n_16802": "Paradise terminal",
    "n_16803": "Highline terminal",
}
SOURCE_LABELS = {
    "n_10434": "Paradise diversion",
    "n_15269": "Hyrum Reservoir",
    "n_15286": "Porcupine Reservoir",
    "n_15957": "Hyrum diversion",
}


def polygon_rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry["type"] == "Polygon":
        yield from geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            yield from polygon
    else:
        raise ValueError(f"Unsupported polygon geometry: {geometry['type']}")


def plot_geometry(ax: Any, geometry: dict[str, Any], **kwargs: Any) -> None:
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(f"Unsupported polygon geometry: {geometry['type']}")
    for polygon in polygons:
        exterior = polygon[0]
        ax.fill(
            [point[0] for point in exterior],
            [point[1] for point in exterior],
            **kwargs,
        )


def open_layer(path: Path) -> Path:
    """Return the layer, or say which file was wanted and where to point the variable."""

    if path.exists():
        return path
    raise SystemExit(
        f"missing open layer {path}\n"
        f"LEXIMIN_DATASETS is currently {DATASETS}; point it at the root that holds "
        f"{path.parent.name}."
    )


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Palatino Linotype", "Palatino", "DejaVu Serif"],
            "svg.fonttype": "none",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    services = json.loads(open_layer(SERVICE_AREAS).read_text(encoding="utf-8"))
    subareas = json.loads(open_layer(SUBAREAS).read_text(encoding="utf-8"))

    node_by_id = {row["node_id"]: row for row in benchmark["nodes"]}
    company_by_terminal = {
        mapping["terminal_node"]: next(
            row["company_id"]
            for row in benchmark["claimants"]
            if row["claimant_id"] == mapping["claimant_id"]
        )
        for mapping in benchmark["claimant_terminals"]
    }
    selected_companies = set(COMPANY_COLORS)
    selected_service_features = [
        feature
        for feature in services["features"]
        if int(feature["properties"].get("COMPANYID", -1)) in selected_companies
    ]
    cache_boundary = next(
        feature
        for feature in subareas["features"]
        if feature["properties"].get("SubArea") == "01-01-04"
    )

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 13.5,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
        }
    )
    # 7.3 in is close to a full-width journal figure. Font sizes are therefore
    # specified at their intended final printed scale instead of relying on a
    # large canvas that would later be reduced by roughly 50%.
    fig, ax = plt.subplots(figsize=(7.3, 6.9), constrained_layout=False)
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.335, top=0.975)

    # Geographic context: only the visible local part of the Cache Valley boundary
    # is shown because the axes are cropped to the three service areas.
    plot_geometry(
        ax,
        cache_boundary["geometry"],
        facecolor="#F4F4F4",
        edgecolor="#A8A8A8",
        linewidth=0.9,
        alpha=0.65,
        zorder=0,
    )

    all_context_points: list[tuple[float, float]] = []
    for feature in selected_service_features:
        company = int(feature["properties"]["COMPANYID"])
        color = COMPANY_COLORS[company]
        plot_geometry(
            ax,
            feature["geometry"],
            facecolor=color,
            edgecolor=color,
            linewidth=1.35,
            alpha=0.13,
            zorder=1,
        )
        for ring in polygon_rings(feature["geometry"]):
            all_context_points.extend((point[0], point[1]) for point in ring)

    max_capacity = max(float(edge["capacity_cfs_base"]) for edge in benchmark["edges"])
    for edge in benchmark["edges"]:
        start = node_by_id[edge["from_node"]]
        end = node_by_id[edge["to_node"]]
        xs = [float(start["longitude"]), float(end["longitude"])]
        ys = [float(start["latitude"]), float(end["latitude"])]
        if edge["edge_role"] == "derived_connector":
            ax.plot(
                xs,
                ys,
                color="#5F6368",
                linewidth=1.5,
                linestyle=(0, (4, 3)),
                alpha=0.9,
                zorder=3,
            )
        else:
            capacity = float(edge["capacity_cfs_base"])
            linewidth = 1.25 + 2.0 * math.sqrt(capacity / max_capacity)
            if edge["flowline_type"] == "stream":
                color = "#0072B2"
                linestyle = "-"
            else:
                color = "#3C5488"
                linestyle = "-"
            ax.annotate(
                "",
                xy=(xs[1], ys[1]),
                xytext=(xs[0], ys[0]),
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": color,
                    "lw": linewidth,
                    "linestyle": linestyle,
                    "alpha": 0.86,
                    "shrinkA": 1.5,
                    "shrinkB": 1.5,
                    "mutation_scale": 8,
                },
                zorder=4,
            )

    junctions = [
        row
        for row in benchmark["nodes"]
        if "source_injection" not in row["roles"] and "delivery_terminal" not in row["roles"]
    ]
    ax.scatter(
        [row["longitude"] for row in junctions],
        [row["latitude"] for row in junctions],
        s=18,
        facecolor="#FFFFFF",
        edgecolor="#444444",
        linewidth=0.7,
        zorder=5,
    )

    for source in benchmark["sources"]:
        node = node_by_id[source["node_id"]]
        reservoir = source["source_class"] == "reservoir_release"
        ax.scatter(
            [node["longitude"]],
            [node["latitude"]],
            s=150 if reservoir else 125,
            marker="s" if reservoir else "^",
            facecolor="#56B4E9" if reservoir else "#D55E00",
            edgecolor="#202124",
            linewidth=1.1,
            zorder=7,
        )
        source_offsets = {
            "n_10434": (7, 9),
            "n_15269": (0, -22),
            # Keep the two lower labels inside the map frame at the intended
            # 14 cm print width.  Hyrum is placed in the open space to the
            # left and slightly lower; Porcupine is anchored to the left of
            # its reservoir so the complete label remains inside the axes.
            "n_15286": (31, -18),
            "n_15957": (-2, 8),
        }
        source_alignment = {
            "n_10434": "left",
            "n_15269": "center",
            "n_15286": "right",
            "n_15957": "right",
        }
        ax.annotate(
            SOURCE_LABELS[source["node_id"]],
            (node["longitude"], node["latitude"]),
            xytext=source_offsets[source["node_id"]],
            textcoords="offset points",
            fontsize=9.4,
            fontweight="medium",
            color="#202124",
            ha=source_alignment[source["node_id"]],
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 0.6},
            zorder=8,
        )

    for terminal, company in company_by_terminal.items():
        node = node_by_id[terminal]
        ax.scatter(
            [node["longitude"]],
            [node["latitude"]],
            s=195,
            marker="*",
            facecolor=COMPANY_COLORS[company],
            edgecolor="#202124",
            linewidth=1.0,
            zorder=8,
        )
        offsets = {
            "n_16801": (8, 8),
            "n_16802": (8, 10),
            "n_16803": (8, -17),
        }
        ax.annotate(
            TERMINAL_LABELS[terminal],
            (node["longitude"], node["latitude"]),
            xytext=offsets[terminal],
            textcoords="offset points",
            fontsize=9.4,
            fontweight="medium",
            color="#202124",
            ha="left",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 0.6},
            zorder=9,
        )

    all_context_points.extend(
        (float(row["longitude"]), float(row["latitude"])) for row in benchmark["nodes"]
    )
    min_lon = min(point[0] for point in all_context_points)
    max_lon = max(point[0] for point in all_context_points)
    min_lat = min(point[1] for point in all_context_points)
    max_lat = max(point[1] for point in all_context_points)
    lon_pad = (max_lon - min_lon) * 0.045
    lat_pad = (max_lat - min_lat) * 0.055
    ax.set_xlim(min_lon - lon_pad, max_lon + 2.8 * lon_pad)
    ax.set_ylim(min_lat - lat_pad, max_lat + lat_pad)
    mean_lat = (min_lat + max_lat) / 2.0
    ax.set_aspect(1.0 / math.cos(math.radians(mean_lat)))

    ax.set_xlabel("Longitude (WGS84)")
    ax.set_ylabel("Latitude (WGS84)")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=7))
    ax.grid(color="#D7D7D7", linewidth=0.55, linestyle=":", alpha=0.75, zorder=0)

    # Compact cartographic cues for the article version. Descriptive counts belong
    # in the manuscript caption rather than in a duplicate title inside the panel.
    ax.annotate(
        "N",
        xy=(0.945, 0.945),
        xytext=(0.945, 0.855),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=10.0,
        fontweight="bold",
        arrowprops={"arrowstyle": "-|>", "color": "#202124", "lw": 1.2},
        zorder=12,
    )
    scale_km = 2.0
    scale_lon = scale_km / (111.32 * math.cos(math.radians(mean_lat)))
    scale_x0 = min_lon + 0.08 * (max_lon - min_lon)
    scale_y0 = min_lat + 0.045 * (max_lat - min_lat)
    ax.plot(
        [scale_x0, scale_x0 + scale_lon],
        [scale_y0, scale_y0],
        color="#202124",
        linewidth=2.0,
        solid_capstyle="butt",
        zorder=12,
    )
    ax.plot(
        [scale_x0, scale_x0],
        [scale_y0 - 0.0012, scale_y0 + 0.0012],
        color="#202124",
        linewidth=1.2,
        zorder=12,
    )
    ax.plot(
        [scale_x0 + scale_lon, scale_x0 + scale_lon],
        [scale_y0 - 0.0012, scale_y0 + 0.0012],
        color="#202124",
        linewidth=1.2,
        zorder=12,
    )
    ax.text(
        scale_x0 + scale_lon / 2.0,
        scale_y0 + 0.0021,
        "2 km",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#202124",
        zorder=12,
    )

    # Two legends rather than one. A canal reach and a path connector are different kinds
    # of thing -- one is a mapped channel, the other a link the model adds to close a gap in
    # the official path table -- and a single flat block gave no sign of that. The two
    # physical entries carry the arrowhead the map draws, so the legend shows what the
    # picture shows.
    link_handles = [
        Line2D([0, 1], [0, 0], color="#3C5488", lw=2.5, marker=">", markevery=[1],
               markersize=6, markerfacecolor="#3C5488", markeredgecolor="#3C5488",
               label="Canal reach"),
        Line2D([0, 1], [0, 0], color="#0072B2", lw=2.5, marker=">", markevery=[1],
               markersize=6, markerfacecolor="#0072B2", markeredgecolor="#0072B2",
               label="Stream reach"),
        Line2D([0], [0], color="#5F6368", lw=1.7, linestyle=(0, (4, 3)),
               label="Path connector"),
    ]
    feature_handles = [
        Line2D([0], [0], marker="^", color="none", markerfacecolor="#D55E00", markeredgecolor="#202124", markersize=9, label="Surface diversion"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#56B4E9", markeredgecolor="#202124", markersize=9, label="Reservoir"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor="#E69F00", markeredgecolor="#202124", markersize=12, label="Terminal"),
    ]
    feature_handles.extend(
        Patch(
            facecolor=color,
            edgecolor=color,
            alpha=0.25,
            label={88: "Hyrum area", 130: "Paradise area", 132: "Highline area"}[company],
        )
        for company, color in COMPANY_COLORS.items()
    )
    common = {
        "loc": "upper center",
        "frameon": True,
        "framealpha": 0.94,
        "facecolor": "#FFFFFF",
        "edgecolor": "#B5B5B5",
        "fontsize": 9.2,
        "columnspacing": 1.25,
        "handlelength": 2.2,
        "handletextpad": 0.65,
        "borderpad": 0.65,
    }
    links = ax.legend(
        handles=link_handles,
        title="Mapped channels (arrow: flow direction) and the logical connector",
        bbox_to_anchor=(0.5, -0.115),
        ncol=3,
        **common,
    )
    links.get_title().set_fontsize(9.2)
    ax.add_artist(links)
    # Where the second legend goes is asked of the first rather than assumed. A constant
    # chosen before either was drawn left a blank band between them, and it would be wrong
    # again, silently, the next time an entry is added to either list.
    fig.canvas.draw()
    below = (
        links.get_window_extent()
        .transformed(ax.transAxes.inverted())
        .y0
        - 0.025
    )
    ax.legend(
        handles=feature_handles,
        title="Nodes and service areas",
        bbox_to_anchor=(0.5, below),
        ncol=3,
        **common,
    ).get_title().set_fontsize(9.2)

    fig.savefig(PNG_OUTPUT, dpi=600, facecolor="white", bbox_inches="tight")
    fig.savefig(SVG_OUTPUT, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print(PNG_OUTPUT)
    print(SVG_OUTPUT)


if __name__ == "__main__":
    main()

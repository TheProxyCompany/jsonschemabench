#!/usr/bin/env python3

import json
import math
import glob
import sys
import os
import re
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


class Stats:
    def __init__(self) -> None:
        self.meta = {}
        self.ttfm_us = 0
        self.max_ttfm_us = 0
        self.masks_us = 0
        self.avg_mask_us = 0
        self.masks_us_under_10ms = 0
        self.num_masks_under_10ms = 0
        self.avg_masks_under_10ms = 0
        self.masks_us_over_10ms = 0
        self.num_masks_over_10ms = 0
        self.avg_masks_over_10ms = 0
        self.max_mask_us = 0
        self.num_tokens = 0
        self.num_schemas = 0
        self.num_crashes_or_timeouts = 0
        self.num_timeouts = 0
        self.num_segv = 0
        self.num_abort = 0
        self.num_schemas_ok = 0
        self.num_compilation_errors = 0
        self.num_validation_errors = 0
        self.num_invalidation_errors = 0
        self.num_tests = 0
        self.num_valid_tests = 0
        self.num_invalid_tests = 0

    def load_json(self, data: dict):
        for k in self.__dict__.keys():
            if k in data:
                self.__dict__[k] = data[k]


def log_fraction_plot(times: list[int]):
    times.sort()
    cutoff = 1
    mult = 1.3
    count = 0
    csv = "cutoff time,frac left\n"
    total = len(times)
    for t in times:
        while t > cutoff:
            csv += f"{cutoff / 1000.0},{(total - count) / total}\n"
            cutoff = int(cutoff * mult) + 1
        count += 1
    return csv


def histogram_position(us: int):
    return int(math.floor(math.log10(max(1, us - 1))))


def us_to_str(us: int):
    if us < 1000:
        return f"{us}us"
    if us < 1000000:
        return f"{us // 1000}ms"
    return f"{us // 1000000}s"


def read_json(filename: str):
    with open(filename) as f:
        data = json.load(f)
    return data


def main(folder: str):
    if not os.path.isdir(folder):
        raise Exception(f"Not a directory: {folder}")
    files = glob.glob(folder + "/*.json")
    files = sorted(files)

    stats = Stats()
    stats.meta = read_json(folder + "/meta.txt")
    ttfm_us = []
    all_masks_us = []
    histogram_us = [0] * 10
    histogram_num = [0] * 10
    for f in files:
        with open(f) as f:
            data = json.load(f)
        elts = [data]
        if isinstance(data, list):
            elts = data
        for data in elts:
            stats.num_schemas += 1
            if "num_tests" not in data:
                stats.num_crashes_or_timeouts += 1
                continue
            stats.num_tests += data["num_tests"]
            if "compile_error" in data:
                stats.num_compilation_errors += 1
            else:
                stats.ttfm_us += data["ttfm_us"]
                ttfm_us.append(data["ttfm_us"])
                stats.max_ttfm_us = max(data["max_ttfm_us"], stats.max_ttfm_us)
                if "masks_us" in data:
                    stats.masks_us += data["masks_us"]
                    stats.max_mask_us = max(data["max_mask_us"], stats.max_mask_us)
                    stats.num_tokens += data["num_tokens"]
                if "validation_error" in data:
                    if "should reject" in data["validation_error"]:
                        stats.num_invalidation_errors += 1
                    else:
                        stats.num_validation_errors += 1
                else:
                    stats.num_schemas_ok += 1
                stats.num_valid_tests += data["num_valid_tests"]
                stats.num_invalid_tests += data["num_invalid_tests"]
                all_masks_us.extend(data["all_mask_us"])
                for us in data["all_mask_us"]:
                    p = histogram_position(us)
                    histogram_us[p] += us
                    histogram_num[p] += 1
                    if us < 10000:
                        stats.masks_us_under_10ms += us
                        stats.num_masks_under_10ms += 1
                    else:
                        stats.masks_us_over_10ms += us
                        stats.num_masks_over_10ms += 1
    # Add safety checks for division by zero
    stats.avg_masks_under_10ms = stats.masks_us_under_10ms // max(
        stats.num_masks_under_10ms, 1
    )
    stats.avg_masks_over_10ms = stats.masks_us_over_10ms // max(
        stats.num_masks_over_10ms, 1
    )
    stats.avg_mask_us = stats.masks_us // max(stats.num_tokens, 1)
    with open(folder + "/stats.txt", "w") as f:
        f.write(json.dumps(stats.__dict__, indent=2))
    with open(folder + "/ttfm_us.csv", "w") as f:
        f.write(log_fraction_plot(ttfm_us))
    with open(folder + "/masks_us.csv", "w") as f:
        f.write(log_fraction_plot(all_masks_us))

    output_file = os.path.join(folder, "log.txt")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    try:
        with open(output_file, "r") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line == "Exit code: -11":
                    stats.num_segv += 1
                elif line == "Exit code: -6":
                    stats.num_abort += 1
                elif line == "Exit code: -14":
                    stats.num_timeouts += 1
    except FileNotFoundError:
        # File doesn't exist yet, create an empty one
        with open(output_file, "w") as f:
            pass

    ps = [25, 50, 75, 90, 95, 99, 99.9, 100]

    def get_p(arr: list[int], p: float):
        idx = int(len(arr) * p / 100)
        if idx >= len(arr):
            idx = len(arr) - 1
        return arr[idx]

    entries = {}
    all_masks_us.sort()

    if all_masks_us:
        entries["TBM avg"] = sum(all_masks_us) // len(all_masks_us)
        for p in ps:
            entries[f"TBM p{p}"] = get_p(all_masks_us, p)
    else:
        entries["TBM avg"] = 0
        for p in ps:
            entries[f"TBM p{p}"] = 0

    ttfm_us += [900_000_000] * stats.num_timeouts
    ttfm_us.sort()

    if ttfm_us:
        entries["TTFM avg"] = sum(ttfm_us) // len(ttfm_us)
        for p in ps:
            entries[f"TTFM p{p}"] = get_p(ttfm_us, p)
    else:
        entries["TTFM avg"] = 0
        for p in ps:
            entries[f"TTFM p{p}"] = 0 # Or perhaps None

    entries["tokens"] = stats.num_tokens
    entries["schemas"] = stats.num_schemas
    entries["passing"] = stats.num_schemas_ok
    entries["crashes"] = stats.num_crashes_or_timeouts
    entries["compile error"] = stats.num_compilation_errors
    entries["segmentation fault"] = stats.num_segv
    entries["out of memory"] = stats.num_abort
    entries["timeout"] = stats.num_timeouts
    entries["validation error"] = stats.num_validation_errors
    entries["invalidation error"] = stats.num_invalidation_errors
    with open(folder + "/entries.txt", "w") as f:
        f.write(json.dumps(entries, indent=2))

    num_masks = sum(histogram_num)
    h_csv = "above us,frac\n"
    # Ensure num_masks is not zero before calculating fractions
    if num_masks > 0:
        for i in range(1, 10): # range(10)[1:] is equivalent to range(1, 10)
            frac = sum(histogram_num[i:]) * 100.0 / num_masks # Use float division
            h_csv += f"{us_to_str(10**i):10}"
            h_csv += ","
            # Ensure frac is formatted correctly, even if very small
            h_csv += f"{frac:.15f}" # Use standard float formatting
            h_csv += "\n"
    else:
        # Handle case where there are no masks (e.g., all errors)
        for i in range(1, 10):
             h_csv += f"{us_to_str(10**i):10}"
             h_csv += ","
             h_csv += f"{0.0:.15f}" # Fraction is zero
             h_csv += "\n"

    with open(folder + "/histogram.csv", "w") as f:
        f.write(h_csv)

    return stats, entries


def markdown_table(data):
    # Determine the column widths
    col_widths = [max(len(row[col]) for row in data) for col in range(len(data[0]))]

    # Generate the Markdown table
    def format_row(row):
        return (
            "| "
            + " | ".join(
                f"{cell:<{col_widths[i]}}" if i == 0 else f"{cell:>{col_widths[i]}}"
                for i, cell in enumerate(row)
            )
            + " |\n"
        )

    r = format_row(data[0])
    r += (
        "|"
        + "|".join(
            ":" + "-" * (width + 1) if i == 0 else "-" * (width + 1) + ":"
            for i, width in enumerate(col_widths)
        )
        + "|\n"
    )

    # Print the rows
    for row in data[1:]:
        r += format_row(row)

    return r


def format_time(time_us: int):
    if time_us < 1_000:
        result = f"{time_us}μs"
    elif time_us < 1_000_000:
        time_ms = time_us / 1_000
        if time_ms < 10:
            result = f"{time_ms:.1f}ms"
        else:
            result = f"{time_ms:.0f}ms"
    else:
        time_s = time_us / 1_000_000
        if time_s < 10:
            result = f"{time_s:.1f}s"
        else:
            result = f"{time_s:.0f}s"
    return result


plot_colors = {
    "llg": "#000000",
    "xgr": 9,
    "llamacpp": 1,
    "xgr-cpp": 0,
    "outlines": 2,
    "pse": "#024645",
}

text_colors = {
    "pse": "#DAD0AF",
}


def plot_metrics(
    id: str,
    keys: list[str],
    title: str,
    data: list[dict[str, Any]],
):
    if not data:
        print(f"Warning: No data provided for plot {id}")
        return

    # Create plots directory if it doesn't exist
    os.makedirs("plots", exist_ok=True)

    engine_list: list[tuple[str, str]] = []
    for idx, data_item in enumerate(data):
        meta: dict[str, Any] = data_item.get("meta", {})
        if not meta:
            print(f"Warning: Missing 'meta' for item at index {idx}")
            continue

        engine_id: str = meta.get("id", f"engine_{idx + 1}")
        engine_name: str = meta.get("name", f"Engine {idx + 1}")

        engine_list.append((engine_id, engine_name))

    values = {}
    labels: dict[str, str] = {
        engine_id: engine_name for engine_id, engine_name in engine_list
    }
    for engine_id, engine_data in zip([id for id, _ in engine_list], data, strict=True):
        key_values = []
        for key in keys:
            if key in engine_data:
                key_values.append(engine_data[key])

        values[engine_id] = key_values

    # Calculate positions
    y = np.arange(len(keys))
    height = 0.8 / max(len(engine_list), 1)

    # Set up the plot
    fig, ax = plt.subplots(figsize=(10, len(keys) + 1))
    bar_positions = []

    cmap = plt.get_cmap("tab10")

    custom_colors = []
    custom_text_colors = []
    for i, (engine_id, _) in enumerate(engine_list):
        if engine_id in plot_colors:
            c = plot_colors[engine_id]
            if isinstance(c, int):
                custom_colors.append(cmap(c))
            else:
                custom_colors.append(c)

            if engine_id in text_colors:
                custom_text_colors.append(text_colors[engine_id])
            else:
                custom_text_colors.append("none")

        else:
            custom_colors.append(cmap(i % 10))
            custom_text_colors.append("none")

    for i, (label, tbm_values) in enumerate(values.items()):
        pos = y + (len(labels) - i - 1) * height - 0.4 + (height / 2)
        bar_positions.append(pos)

        # Handle potential zero values (use small value instead)
        safe_values = [max(v, 0.1) for v in tbm_values]

        background_color = custom_colors[i % len(custom_colors)]
        # foreground_color = custom_text_colors[i % len(custom_text_colors)]

        bars = ax.barh(
            pos,
            safe_values,
            height,
            label=label,
            color=background_color,
        )

        # Add annotations on the bars
        for j, (bar, value) in enumerate(zip(bars, tbm_values)):
            # Skip annotation if value is too small
            if value < 0.1:
                continue

            label_text = format_time(value)
            # Ensure text is positioned correctly
            text_x = max(bar.get_width() * 1.1, 1)
            ax.text(
                text_x,
                bar.get_y() + bar.get_height() / 2,
                label_text,
                ha="left",
                va="center",
                fontsize=8,
                rotation=0,
                color=background_color,
            )

    # Configure axes
    ax.set_xscale("log", base=10)
    ax.set_yticks(y)
    ax.set_yticklabels(keys, rotation=45, ha="right")
    ax.set_xlabel("Time (log scale, microseconds)")
    ax.set_title(title)
    ax.legend([engine_name for _, engine_name in engine_list], loc="best")

    # Adjust y-axis limit to accommodate legend
    current_ylim_bottom, current_ylim_top = ax.get_ylim()
    ax.set_ylim(
        bottom=current_ylim_bottom,
        top=current_ylim_top + (0.1 * len(engine_list)),
    )

    # Adjust x-axis limit to accommodate text annotations
    current_xlim_left, current_xlim_right = ax.get_xlim()
    ax.set_xlim(
        left=current_xlim_left,
        right=current_xlim_right * 1.15,
    )

    plt.tight_layout()

    try:
        plt.savefig(f"plots/{id}.png", dpi=300)
    except Exception as e:
        print(f"Error saving plot: {e}")

    plt.close()


if __name__ == "__main__":
    folder = sys.argv[1]

    metas = glob.glob(folder + "/*/meta.txt")
    folders = [os.path.dirname(m) for m in metas]

    ents: list[dict] = []
    all_stats: list[Stats] = []
    hd = ["metric"]

    for fld in folders:
        stats, entries = main(fld)
        entries["meta"] = stats.meta
        ents.append(entries)
        all_stats.append(stats)

    positions = list(plot_colors.keys())
    ents.sort(key=lambda e: positions.index(e["meta"]["id"]))
    if len(ents) == 0:
        print("Warning: No data available for plotting")
        exit(1)

    hd += [e["meta"]["name"] for e in ents]
    rows = [hd]
    for k in ents[0].keys():
        if k == "meta":
            continue
        line = [k]
        for e in ents:
            line.append(f"{e[k]:,}")
        rows.append(line)
    tbl = markdown_table(rows)

    tbl += "\n\n### Versions\n\n"
    seen_modules = set()
    for st in ents:
        meta = st["meta"]
        module = meta["module"]
        if module in seen_modules:
            continue
        seen_modules.add(module)
        tbl += f"* {module}: {meta['module_version']}\n"

    with open("README.md", "r") as f:
        rdm = f.read()
        rdm = re.sub(
            r"<!-- GEN-BEGIN -->.*?<!-- GEN-END -->",
            "<!-- GEN-BEGIN -->\n" + tbl + "<!-- GEN-END -->",
            rdm,
            flags=re.DOTALL,
        )
    with open("README.md", "w") as f:
        f.write(rdm)

    keys = ents[0].keys()

    # Check if we have enough data to generate plots
    if len(ents) < 1:
        print("Warning: Not enough data to generate comparison plots")
    else:
        # Extract available keys for plotting
        all_keys = set()
        for e in ents:
            all_keys.update(e.keys())
        all_keys.discard("meta")  # Don't include meta in plotting keys

        # Find TBM and TTFM keys that exist in the data
        tbm_keys = [
            k for k in all_keys if k.startswith("TBM ") and all(k in e for e in ents)
        ]
        ttfm_keys = [
            k for k in all_keys if k.startswith("TTFM ") and all(k in e for e in ents)
        ]

        # Check if we have average keys for hero plot
        has_tbm_avg = "TBM avg" in all_keys and all("TBM avg" in e for e in ents)
        has_ttfm_avg = "TTFM avg" in all_keys and all("TTFM avg" in e for e in ents)

        if tbm_keys:
            plot_metrics(
                keys=tbm_keys,
                id="tbm",
                title="Per-token mask computation time (Time Between Masks aka TBM)",
                data=ents,
            )
        else:
            print("Warning: No TBM data available for plotting")

        if ttfm_keys:
            plot_metrics(
                keys=ttfm_keys,
                id="ttfm",
                title="Grammar compilation (Time To First Mask aka TTFM); 900s timeout",
                data=ents,
            )
        else:
            print("Warning: No TTFM data available for plotting")

        if has_tbm_avg and has_ttfm_avg:
            plot_metrics(
                keys=["TTFM avg", "TBM avg"],
                id="hero",
                title="Time To First Mask (TTFM) and Time Between Masks (TBM)",
                data=ents,
            )
        else:
            print("Warning: Missing average data for hero plot")

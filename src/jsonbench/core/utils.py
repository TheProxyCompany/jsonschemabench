import os
import sys
import random
import string
import numpy as np
from dacite import from_dict
from omegaconf import OmegaConf
import matplotlib.pyplot as plt
from prettytable import PrettyTable
from contextlib import contextmanager
from typing import List, Optional, TypeVar, Type, TYPE_CHECKING, Callable


if TYPE_CHECKING:
    from core.types import Metric, AggregatedPerfMetrics

GENERATION_TIMEOUT = 60
COMPILATION_TIMEOUT = 10


T = TypeVar("T")


def load_config(config_type: Type[T], config_path: str) -> T:
    return from_dict(data_class=config_type, data=OmegaConf.load(config_path))


def safe_divide(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Safely divides a by b, returning None if either input is None."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def safe_subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Safely subtracts b from a, returning None if either input is None."""
    if a is None or b is None:
        return None
    return a - b


def safe_min(a: int, b: Optional[int]) -> int:
    if b is None:
        return a
    return min(a, b)


def format_metric(metric: "Metric", details: bool = False) -> str:
    if (
        metric.median is None
        or metric.std is None
        or metric.min is None
        or metric.max is None
    ):
        return "n/a"
    return f"{metric.median:.2f} ± {metric.std:.2f}" + (
        f"\n[{metric.min:.2f} - {metric.max:.2f}]" if details else ""
    )


@contextmanager
def disable_print():
    stdout = sys.stdout
    stderr = sys.stderr
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    try:
        yield
    finally:
        sys.stdout = stdout
        sys.stderr = stderr


def nanoid(length: int = 4) -> str:
    return "".join(random.choices(string.ascii_letters, k=length))


def bootstrap(
    data: List[float], func: Callable[[List[float]], float], n_samples: int = 100
) -> List[float]:
    samples = []
    for _ in range(n_samples):
        sample = random.choices(data, k=len(data))
        samples.append(func(sample))
    return samples


def print_scores(
    declared_coverage: List["Metric"],
    empirical_coverage: List["Metric"],
    compliance: List["Metric"],
    perf_metrics: List["AggregatedPerfMetrics"],
    output_tokens: List["Metric"],
    tasks: List[str],
    details: bool = False,
) -> None:
    columns = [
        "Task",
        "Declared coverage",
        "Empirical coverage",
        "Compliance",
        "TTFT (s)",
        "TPOT (ms)",
        "TGT (s)",
        "GCT (s)",
        "Output tokens",
    ]

    table = PrettyTable(columns)
    for task, dc, ec, cl, pm, ot in zip(
        tasks,
        declared_coverage,
        empirical_coverage,
        compliance,
        perf_metrics,
        output_tokens,
    ):
        row = [
            task,
            format_metric(dc, details),
            format_metric(ec, details),
            format_metric(cl, details),
            format_metric(pm.ttft, details),
            format_metric(pm.tpot, details),
            format_metric(pm.tgt, details),
            format_metric(pm.gct, details),
            format_metric(ot, details),
        ]

        table.add_row(row, divider=details)
    print(table)


def plot_perf_metrics(
    perf_metrics: List["AggregatedPerfMetrics"],
    tasks: List[str],
    path: str,
    engine_name: str,
) -> None:
    metric_names = ["TTFT", "TPOT", "TGT", "GCT"]

    valid_tasks = []
    valid_metrics = []
    for task, pm in zip(tasks, perf_metrics):
        if (
            pm.ttft
            and pm.ttft.values
            or pm.tpot
            and pm.tpot.values
            or pm.tgt
            and pm.tgt.values
            or pm.gct
            and pm.gct.values
        ):
            valid_tasks.append(task)
            valid_metrics.append(pm)

    if not valid_tasks:
        print("No valid metrics data found for any task.")
        return

    fig, axs = plt.subplots(
        nrows=len(valid_tasks),
        ncols=len(metric_names),
        figsize=(5 * len(metric_names), 4 * len(valid_tasks)),
        sharex="col",
    )

    if len(valid_tasks) == 1:
        axs = np.array([axs])

    all_metrics_data = {
        "TTFT": [],
        "TPOT": [],
        "TGT": [],
        "GCT": [],
    }

    for pm in valid_metrics:
        all_metrics_data["TTFT"].extend(
            pm.ttft.values if pm.ttft and pm.ttft.values else []
        )
        all_metrics_data["TPOT"].extend(
            pm.tpot.values if pm.tpot and pm.tpot.values else []
        )
        all_metrics_data["TGT"].extend(
            pm.tgt.values if pm.tgt and pm.tgt.values else []
        )
        all_metrics_data["GCT"].extend(
            pm.gct.values if pm.gct and pm.gct.values else []
        )

    bin_intervals = {}
    for metric_name in metric_names:
        if all_metrics_data[metric_name]:
            bin_intervals[metric_name] = np.linspace(
                min(all_metrics_data[metric_name]),
                max(all_metrics_data[metric_name]),
                20,
            )
        else:
            bin_intervals[metric_name] = None

    for j, metric_name in enumerate(metric_names):
        unit = "ms" if metric_name == "TPOT" else "seconds"
        axs[0, j].set_title(f"{metric_name} ({unit})", fontsize=14)

    for i, (task, pm) in enumerate(zip(valid_tasks, valid_metrics)):
        axs[i, 0].set_ylabel(task, fontsize=12, rotation=45, ha="right")

        metrics_data = {
            "TTFT": pm.ttft.values if pm.ttft and pm.ttft.values else [],
            "TPOT": pm.tpot.values if pm.tpot and pm.tpot.values else [],
            "TGT": pm.tgt.values if pm.tgt and pm.tgt.values else [],
            "GCT": pm.gct.values if pm.gct and pm.gct.values else [],
        }

        for j, metric_name in enumerate(metric_names):
            if metrics_data[metric_name]:
                if bin_intervals[metric_name] is not None:
                    axs[i, j].hist(
                        metrics_data[metric_name],
                        bins=bin_intervals[metric_name],
                        alpha=0.7,
                        color="skyblue",
                        edgecolor="black",
                    )
                else:
                    if len(metrics_data[metric_name]) > 1:
                        bins = np.linspace(
                            min(metrics_data[metric_name]),
                            max(metrics_data[metric_name]),
                            20,
                        )
                    else:
                        value = metrics_data[metric_name][0]
                        bins = np.linspace(max(0, value * 0.9), value * 1.1, 20)

                    axs[i, j].hist(
                        metrics_data[metric_name],
                        bins=bins,
                        alpha=0.7,
                        color="skyblue",
                        edgecolor="black",
                    )

                if i == len(valid_tasks) - 1:
                    axs[i, j].set_xlabel(f"Value ({unit})")

                if len(metrics_data[metric_name]) > 0:
                    mean_val = np.mean(metrics_data[metric_name])
                    median_val = np.median(metrics_data[metric_name])
                    axs[i, j].axvline(
                        mean_val,
                        color="red",
                        linestyle="--",
                        linewidth=1.5,
                        label=f"Mean: {mean_val:.2f}",
                    )
                    axs[i, j].axvline(
                        median_val,
                        color="green",
                        linestyle=":",
                        linewidth=1.5,
                        label=f"Median: {median_val:.2f}",
                    )
                    axs[i, j].legend(fontsize=8)
            else:
                axs[i, j].text(
                    0.5,
                    0.5,
                    "No data",
                    ha="center",
                    va="center",
                    transform=axs[i, j].transAxes,
                )

    for j, metric_name in enumerate(metric_names):
        if bin_intervals[metric_name] is not None:
            for i in range(len(valid_tasks)):
                axs[i, j].set_xlim(
                    bin_intervals[metric_name][0], bin_intervals[metric_name][-1]
                )

    fig.suptitle(f"Performance Metrics for {engine_name}", fontsize=16, y=0.99)
    plt.tight_layout()
    plt.subplots_adjust(top=0.95, wspace=0.3, hspace=0.4)

    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved plot to {path}")

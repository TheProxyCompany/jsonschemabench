from json import loads
from typing import Dict, List
from argparse import ArgumentParser
from dacite import from_dict, Config

from core.evaluator import evaluate
from core.types import GenerationOutput
from core.utils import print_scores, plot_perf_metrics

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--outputs", type=str, required=True)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    dacite_config = Config(check_types=False)
    with open(args.outputs, "r") as f:
        engine_config = loads(f.readline())
        outputs = [
            from_dict(GenerationOutput, loads(line), config=dacite_config)
            for line in f.readlines()[1:]
        ]

    task_outputs: Dict[str, List[GenerationOutput]] = {}
    for output in outputs:
        if output.task not in task_outputs:
            task_outputs[output.task] = []
        task_outputs[output.task].append(output)

    compliance = []
    perf_metrics = []
    output_tokens = []
    declared_coverage = []
    empirical_coverage = []
    for outputs in task_outputs.values():
        dc, ec, cl, pm, ot = evaluate(outputs)

        compliance.append(cl)
        perf_metrics.append(pm)
        declared_coverage.append(dc)
        empirical_coverage.append(ec)
        output_tokens.append(ot)

    print(engine_config)
    print_scores(
        declared_coverage,
        empirical_coverage,
        compliance,
        perf_metrics,
        output_tokens,
        list(task_outputs.keys()),
        args.details,
    )

    if args.details:
        plot_perf_metrics(
            perf_metrics,
            list(task_outputs.keys()),
            f"{args.outputs.split('.')[0]}.png",
            engine_config["engine"],
        )

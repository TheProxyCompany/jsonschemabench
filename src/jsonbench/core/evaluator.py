import numpy as np
from uuid import UUID
from json import loads
from typing import List, Tuple
from ipaddress import IPv4Address, IPv6Address
from jsonschema import Draft202012Validator, FormatChecker, SchemaError

from core.utils import bootstrap
from core.types import (
    Schema,
    CompileStatusCode,
    GenerationOutput,
    AggregatedPerfMetrics,
    Metric,
)


def is_json_schema_valid(schema: Schema):
    try:
        Draft202012Validator.check_schema(schema)
        return True
    except SchemaError:
        return False


format_checker = FormatChecker()


@format_checker.checks("ipv4")
def ipv4_check(value):
    IPv4Address(value)


@format_checker.checks("ipv6")
def ipv6_check(value):
    IPv6Address(value)


@format_checker.checks("uuid")
def uuid_check(value):
    UUID(value)


def validate_json_schema(instance: Schema, schema: Schema) -> bool:
    if not is_json_schema_valid(schema):
        return False
    validator = Draft202012Validator(schema, format_checker=format_checker)
    try:
        validator.validate(instance)

    # we catch all exceptions include ValidationError and Error from extension validators
    except Exception:
        return False
    return True


def evaluate(
    outputs: List[GenerationOutput],
) -> Tuple[Metric, Metric, Metric, AggregatedPerfMetrics, Metric]:
    output_tokens_list = []
    declared_coverage_list = []
    empirical_coverage_list = []

    for generation_output in outputs:
        generation = generation_output.generation
        schema = generation_output.schema

        if schema is None or generation is None:
            continue

        if generation_output.metadata.compile_status.code == CompileStatusCode.OK:
            declared_coverage_list.append(1)
        else:
            declared_coverage_list.append(0)

        try:
            json_object = loads(generation)
        except Exception:
            empirical_coverage_list.append(0)
            continue

        if not validate_json_schema(json_object, schema):
            empirical_coverage_list.append(0)
            continue

        empirical_coverage_list.append(1)
        output_tokens_list.append(generation_output.token_usage.output_tokens)

    ttft_list = [
        generation_output.perf_metrics.ttft
        for generation_output in outputs
        if generation_output.perf_metrics.ttft is not None
    ]
    tpot_list = [
        generation_output.perf_metrics.tpot
        for generation_output in outputs
        if generation_output.perf_metrics.tpot is not None
    ]
    tgt_list = [
        generation_output.perf_metrics.tgt
        for generation_output in outputs
        if generation_output.perf_metrics.tgt is not None
    ]
    gct_list = [
        generation_output.perf_metrics.gct
        for generation_output in outputs
        if generation_output.perf_metrics.gct is not None
    ]

    compliance_list = [
        ec for ec, dc in zip(empirical_coverage_list, declared_coverage_list) if dc == 1
    ]

    dc_mean_list = bootstrap(declared_coverage_list, np.mean)
    ec_mean_list = bootstrap(empirical_coverage_list, np.mean)
    c_mean_list = bootstrap(compliance_list, np.mean)

    return (
        Metric(
            values=dc_mean_list,
            median=np.median(dc_mean_list),
            min=min(dc_mean_list),
            max=max(dc_mean_list),
            std=np.std(dc_mean_list),
        ),
        Metric(
            values=ec_mean_list,
            median=np.median(ec_mean_list),
            min=min(ec_mean_list),
            max=max(ec_mean_list),
            std=np.std(ec_mean_list),
        ),
        Metric(
            values=c_mean_list,
            median=np.median(c_mean_list),
            min=min(c_mean_list),
            max=max(c_mean_list),
            std=np.std(c_mean_list),
        ),
        AggregatedPerfMetrics(
            ttft=Metric(
                values=ttft_list,
                median=np.median(ttft_list),
                min=min(ttft_list),
                max=max(ttft_list),
                std=np.std(ttft_list),
            ),
            tpot=Metric(
                values=tpot_list,
                median=np.median(tpot_list),
                min=min(tpot_list),
                max=max(tpot_list),
                std=np.std(tpot_list),
            ),
            tgt=Metric(
                values=tgt_list,
                median=np.median(tgt_list),
                min=min(tgt_list),
                max=max(tgt_list),
                std=np.std(tgt_list),
            ),
            gct=Metric(
                values=gct_list,
                median=np.median(gct_list),
                min=min(gct_list),
                max=max(gct_list),
                std=np.std(gct_list),
            ),
        ),
        Metric(
            values=output_tokens_list,
            median=np.median(output_tokens_list),
            min=min(output_tokens_list),
            max=max(output_tokens_list),
            std=np.std(output_tokens_list),
        ),
    )

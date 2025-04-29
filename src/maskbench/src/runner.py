#!/usr/bin/env python3

import sys
import json
import os
import random
import time
import resource
import argparse
import traceback
import asyncio
import aiofiles
import aiofiles.os

from src.maskbench.src.engine import Engine
from transformers.models.auto.tokenization_auto import AutoTokenizer


def time_us(prev: float) -> int:
    return int((time.monotonic() - prev) * 1000000)


async def process_file(engine: Engine, file: str):
    id = os.path.basename(file)
    output_name = os.path.join(output_path, id)

    if engine.multi:
        if await aiofiles.os.path.exists(output_name):
            return None

        try:
            async with aiofiles.open(output_name, "x") as f:
                await f.write(json.dumps({"pending_file": 1}, indent=2))
        except FileExistsError:
            return None

    async with aiofiles.open(file) as f:
        pos_data = json.loads(await f.read())

    all_mask_us = []
    status = {
        "id": id,
        "ttfm_us": 0,
        "max_ttfm_us": 0,
        "masks_us": 0,
        "max_mask_us": 0,
        "num_tokens": 0,
        "num_tests": len(pos_data["tests"]),
        "all_mask_us": all_mask_us,
        "num_valid_tests": 0,
        "num_invalid_tests": 0,
    }

    try:
        t0 = time.monotonic()
        engine.compile_grammar(pos_data["schema"])
    except Exception as e:
        if not engine.multi:
            traceback.print_exc()
        status["compile_error"] = repr(e)
        async with aiofiles.open(output_name, "w") as f:
            await f.write(json.dumps(status, indent=2))
        return status

    status["ttfm_us"] = time_us(t0)
    status["max_ttfm_us"] = status["ttfm_us"]

    masks_us = 0
    max_mask_us = 0
    num_tokens = 0

    for i, test in enumerate(pos_data["tests"]):
        engine.reset()

        instance = json.dumps(test["data"], indent=None, ensure_ascii=False)
        tokens = engine.tokenizer.encode(instance, add_special_tokens=False)

        accepted = True
        try:
            for tidx, t in enumerate(tokens):
                t2 = time.monotonic()
                engine.compute_mask()
                ok = engine.commit_token(t)
                mask_time = time_us(t2)
                num_tokens += 1
                masks_us += mask_time
                all_mask_us.append(mask_time)
                if mask_time > max_mask_us:
                    max_mask_us = mask_time
                if not ok:
                    accepted = False
                    break

            if accepted and not test["valid"]:
                status["validation_error"] = f"test #{i}: should reject but didn't"
            elif not accepted and test["valid"]:
                status["validation_error"] = f"test #{i}: should accept but didn't"
            else:
                if test["valid"]:
                    status["num_valid_tests"] += 1
                else:
                    status["num_invalid_tests"] += 1

        except Exception as e:
            if not engine.multi:
                traceback.print_exc()
            status["validation_error"] = f"test #{i}: EXN {repr(e)}"
            accepted = False

    status["masks_us"] = masks_us
    status["max_mask_us"] = max_mask_us
    status["num_tokens"] = num_tokens

    st = json.dumps(status, indent=2)
    engine.log_single(st)
    async with aiofiles.open(output_name, "w") as f:
        await f.write(st)

    return status


def setup_argparse():
    parser = argparse.ArgumentParser(description="Run mask computation.")
    parser.add_argument(
        "--pse", action="store_true", help="Enable Proxy Structuring Engine"
    )
    parser.add_argument("--xgr", action="store_true", help="Enable XGrammar")
    parser.add_argument(
        "--xgr-cpp",
        action="store_true",
        help="Enable XGrammar with JSON->ENBF from llama.cpp",
    )
    parser.add_argument(
        "--xgr-compliant",
        action="store_true",
        help="Enable XGrammar in compliant (non-strict, any whitespace) mode",
    )
    parser.add_argument("--llg", action="store_true", help="Enable LLGuidance")
    parser.add_argument("--outlines", action="store_true", help="Enable Outlines")
    parser.add_argument(
        "--llamacpp", action="store_true", help="Enable llama.cpp grammars"
    )
    parser.add_argument("--output", type=str, help="Output path")
    parser.add_argument(
        "--tokenizer",
        type=str,
        default="unsloth/Llama-3.2-1B",
        help="Tokenizer model ID",
    )

    parser.add_argument(
        "--time-limit", type=int, default=900, help="Time limit in seconds"
    )
    parser.add_argument(
        "--mem-limit", type=int, default=40, help="Memory (RSS) limit in gigabytes"
    )

    defl_cpu = min(os.cpu_count() or 1, 40)
    parser.add_argument(
        "--num-threads",
        "-t",
        type=int,
        default=defl_cpu,
        help="Number of threads to run",
    )

    parser.add_argument(
        "--chunk-size",
        "-c",
        type=int,
        default=100,
        help="Number of files to process per batch (for orchestrator)",
    )

    parser.add_argument(
        "--multi", action="store_true", help="Enable running from run_maskbench.py"
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug output")

    parser.add_argument(
        "files", metavar="file", type=str, nargs="+", help="List of files to process"
    )

    return parser


def get_engine(args) -> Engine:
    engine: Engine | None = None

    if args.xgr or args.xgr_compliant or args.xgr_cpp:
        from src.maskbench.src.xgr_engine import XgrEngine

        assert not engine, "Multiple engines specified"
        engine = XgrEngine()
        engine.compliant = args.xgr_compliant
        engine.llama_cpp = args.xgr_cpp

    if args.pse:
        from src.maskbench.src.pse_engine import PSEEngine

        assert not engine, "Multiple engines specified"
        engine = PSEEngine()

    if args.llg:
        from src.maskbench.src.llg_engine import LlgEngine

        assert not engine, "Multiple engines specified"
        engine = LlgEngine()

    if args.outlines:
        from src.maskbench.src.outlines_engine import OutlinesEngine

        assert not engine, "Multiple engines specified"
        engine = OutlinesEngine()

    if args.llamacpp:
        from src.maskbench.src.llamacpp_engine import LlamaCppEngine

        assert not engine, "Multiple engines specified"
        engine = LlamaCppEngine()

    if not engine:
        raise Exception("No grammar engine specified")

    engine.multi = args.multi
    engine.tokenizer_model_id = args.tokenizer
    engine.debug = args.debug

    return engine


def get_output(args):
    if args.output:
        return args.output
    else:
        id = get_engine(args).get_id()
        return f"tmp/out--{id}"


def main():
    global output_path

    parser = setup_argparse()
    args = parser.parse_args()

    if sys.platform.startswith("linux"):
        limit_gb = args.mem_limit
        limit_bytes = limit_gb * 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

    time_limit_s = args.time_limit

    engine = get_engine(args)
    output_path = get_output(args)

    engine.tokenizer = AutoTokenizer.from_pretrained(
        engine.tokenizer_model_id, trust_remote_code=True
    )

    engine.init()

    files = args.files
    print(f"{len(files)} files, timeout {time_limit_s}s", file=sys.stderr)
    random.shuffle(files)

    os.makedirs(output_path, exist_ok=True)

    async def process_all_files(
        engine: Engine,
        files: list[str],
    ):
        results = []
        for file in files:
            print(f"Processing {file}...")
            result = await process_file(engine, file)
            if result is not None:
                results.append(result)

        return results

    results = asyncio.run(process_all_files(engine, files))

    successful_runs = 0
    failed_runs = 0
    skipped_runs = 0

    if results:
        print(
            f"\n--- Processing Summary ({len(results)} total tasks) ---",
            file=sys.stderr,
        )
        for i, res in enumerate(results):
            if isinstance(res, asyncio.CancelledError):
                failed_runs += 1
                print(f"Result {i}: Task cancelled (timeout).", file=sys.stderr)
            elif isinstance(res, Exception):
                failed_runs += 1
                print(
                    f"Result {i}: Task failed: {type(res).__name__}: {res}",
                    file=sys.stderr,
                )
            elif res is None:
                skipped_runs += 1
            elif isinstance(res, dict):
                successful_runs += 1
            else:
                failed_runs += 1
                print(
                    f"Result {i}: Unexpected result type: {type(res).__name__}",
                    file=sys.stderr,
                )
        print(
            f"--- Summary: {successful_runs} succeeded, {failed_runs} failed, {skipped_runs} skipped ---",
            file=sys.stderr,
        )
    else:
        print("Processing yielded no results list or was empty.", file=sys.stderr)


if __name__ == "__main__":
    main()

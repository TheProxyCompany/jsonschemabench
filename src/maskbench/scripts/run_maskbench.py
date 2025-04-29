#!/usr/bin/env python3
import glob
import random
import subprocess
import os
from threading import Event, Lock, Thread
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback

# --- Keep these functions mostly as they are ---
cmd = ["python3", "-m", "src.maskbench", "--multi"]  # Base command
log_lock = Lock()
print_lock = Lock()


def run_cmd(file_list_chunk: list[str], time_limit: int) -> int:
    if not file_list_chunk:
        return 0

    command = cmd + file_list_chunk
    processed_count_in_chunk = 0
    try:
        chunk_timeout_s = time_limit * len(file_list_chunk) + 60
        subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=chunk_timeout_s,
        )
        processed_count_in_chunk = len(file_list_chunk)
    except subprocess.TimeoutExpired as e:
        stderr = e.stderr or b""

        processed_count_in_chunk = 0
        raise TimeoutError(
            f"Timeout processing chunk starting with {file_list_chunk[0]}"
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        raise Exception(f"Error processing chunk:\n{stderr}") from e
    except Exception as e:  # Catch other potential errors
        raise Exception(f"UNEXPECTED ERROR during run_cmd: {e}") from e

    return processed_count_in_chunk


def get_files(file_paths: list[str]) -> list[str]:
    # (Keep your existing get_files logic)
    file_list = []
    for path in file_paths:
        if path.endswith(".json"):
            file_list.append(path)
        elif os.path.isdir(path):
            json_files = glob.glob(os.path.join(path, "**/*.json"), recursive=True)
            file_list.extend(json_files)
    return list(set(file_list))


def update_progress(
    num_processed: int,
    num_all_files: int,
    num_pending_chunks: int,
    t0: float,
    active_threads: int = 0,
) -> bool:
    now = time.monotonic() - t0
    effective_processed = min(num_processed, num_all_files)
    perc_done = (effective_processed / num_all_files * 100) if num_all_files > 0 else 0

    def format_time(seconds):
        if seconds < 0:
            return "0s"
        if seconds < 60:
            return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60)
        if m < 60:
            return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    eta_str = "--"

    if effective_processed > 5 and perc_done < 99.9:
        time_per_file = now / effective_processed
        remaining_files = num_all_files - effective_processed
        eta_seconds = time_per_file * remaining_files
        eta_str = format_time(eta_seconds)
    elif effective_processed >= num_all_files:
        eta_str = "Done"

    elapsed_str = format_time(now)
    bar_length = 30
    filled_length = min(bar_length, int(bar_length * perc_done / 100))
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    status = f"\r[{bar}] {effective_processed}/{num_all_files} ({min(perc_done, 100.0):.1f}%) | Pending: {num_pending_chunks} | ETA: {eta_str} | Elapsed: {elapsed_str}"
    status += " " * 10 + "\033[?25l"

    with print_lock:
        sys.stdout.write(status)
        sys.stdout.flush()
    return True


# --- /End standard functions ---
def process_chunks_in_threads(file_list: list[str], thread_count: int, chunk_size: int, time_limit: int):
    """
    Processes files in chunks using a ThreadPoolExecutor, where each thread
    runs a subprocess for one chunk.
    """
    global output_path  # Ensure output_path is accessible

    max_thread_count = os.cpu_count() or 1
    thread_count = min(thread_count, max_thread_count)
    min_files_per_thread = max(1, len(file_list) // thread_count)
    lower_bound = max(min_files_per_thread, min(25, len(file_list)))
    optimal_chunk_size = min(chunk_size, lower_bound) if len(file_list) > 0 else 1

    num_all_files = len(file_list)
    if num_all_files == 0:
        print("No files to process.")
        return

    random.shuffle(file_list)
    chunks = [
        file_list[i : i + optimal_chunk_size]
        for i in range(0, len(file_list), optimal_chunk_size)
    ]
    num_chunks = len(chunks)
    num_processed_files = 0
    progress_lock = Lock()
    stop_event = Event()
    t0 = time.monotonic()

    print(f"Total files: {num_all_files} | Chunk size: {optimal_chunk_size}")
    print(f"Using {thread_count} workers to process {num_chunks} chunks")

    def progress_monitor():
        while not stop_event.is_set():
            with progress_lock:
                pending_count = num_all_files - num_processed_files

            update_progress(
                num_processed_files, num_all_files, pending_count, t0, thread_count
            )
            time.sleep(0.2)

            if pending_count == 0:
                break

    thread = Thread(target=progress_monitor)
    thread.start()

    executor = ThreadPoolExecutor(max_workers=thread_count - 1)

    futures = {executor.submit(run_cmd, chunk, time_limit) for chunk in chunks}

    for future in as_completed(futures):
        result = future.result()
        with progress_lock:
            num_processed_files += result

            if num_processed_files > 0:
                update_progress(num_processed_files, num_all_files, 0, t0, 0)

    stop_event.set()
    thread.join()
    # Final newline after progress bar and restore cursor visibility
    sys.stdout.write("\r\033[?25h\n")
    sys.stdout.flush()


# --- Main Execution ---
def main():
    from src.maskbench.src.runner import setup_argparse, get_output, get_engine

    parser = setup_argparse()
    args = parser.parse_args()  # Parse args for the orchestrator

    # Get output path *once* using the parsed args
    output_path = get_output(args)
    os.makedirs(output_path, exist_ok=True)

    file_list = get_files(args.files)
    if not file_list:
        print("No input files found. Exiting.")
        sys.exit(1)

    args_to_pass_to_worker = [arg for arg in sys.argv[1:] if arg not in args.files]
    cmd.extend(args_to_pass_to_worker)

    # --- Logging Meta Information ---
    try:
        # Create a temporary engine instance just to get metadata if needed
        # This still runs get_engine once in the orchestrator, but not the expensive init/tokenizer load
        temp_engine = get_engine(args)
        engine_id = temp_engine.get_id()
        engine_name = temp_engine.get_name()
        engine_module = temp_engine.get_module()
        engine_version = temp_engine.get_version()
    except Exception as e:
        print(f"Warning: Could not get engine metadata: {e}", file=sys.stderr)
        engine_id, engine_name, engine_module, engine_version = (
            "unknown",
            "unknown",
            "unknown",
            "unknown",
        )

    info = f"{len(file_list)} files, "
    info += f"timeout {args.time_limit}s/file, "
    info += f"memory limit {args.mem_limit}GB"
    print(info)

    meta_file_path = os.path.join(output_path, "meta.txt")  # Or meta.json
    try:
        with open(meta_file_path, "w", encoding="utf-8") as meta:
            json.dump(
                {
                    "id": engine_id,
                    "name": engine_name,
                    "module": engine_module,
                    "module_version": engine_version,
                    "base_cmd": cmd,
                    "orchestrator_args": vars(args),
                    "info": info,
                },
                meta,
                indent=2,
            )
    except Exception as e:
        print(
            f"Warning: Could not write meta file {meta_file_path}: {e}", file=sys.stderr
        )

    # --- Run the Processing ---
    try:
        process_chunks_in_threads(
            file_list,
            thread_count=args.num_threads,
            chunk_size=args.chunk_size,
            time_limit=args.time_limit,
        )
    except KeyboardInterrupt:
        sys.stdout.write("\r\033[?25h\n")  # Ensure cursor is visible
        sys.stdout.flush()
        print("\nProcess interrupted by user.")
        # Note: Subprocesses might continue running briefly
        sys.exit(1)
    except Exception as e:
        sys.stdout.write("\r\033[?25h\n")  # Ensure cursor is visible
        sys.stdout.flush()
        print(f"\nAn unexpected error occurred in the orchestrator: {e}")
        traceback.print_exc()
        sys.exit(1)
    # --- / Run the Processing ---


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:
        print(f"{e}")
        traceback.print_exc()
        sys.exit(1)

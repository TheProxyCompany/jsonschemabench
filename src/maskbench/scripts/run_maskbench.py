#!/usr/bin/env python3
import subprocess
import os
import threading
from threading import Lock
import random
import sys
import json
import time

output_path = "tmp/output/"
cmd = ["python3", "-m", "src.maskbench.src.runner", "--multi"]
log_lock = Lock()
print_lock = Lock()


def run_cmd(file_list: list[str]):
    command = cmd + file_list
    log_entry = f"Running command: {' '.join(command)}\n"
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        log_entry += f"{result.stderr}{result.stdout}\nExit code: {result.returncode}\n"
    except Exception as e:
        log_entry += f"Error running command: {e}\n"
    append_to_log(log_entry)


def append_to_log(entry: str):
    log_file = os.path.join(output_path, "log.txt")
    with log_lock:
        with open(log_file, "a") as log:
            log.write(entry + "\n")


def missing_files(file_list: list[str]):
    r = [
        f
        for f in file_list
        if not os.path.exists(os.path.join(output_path, os.path.basename(f)))
    ]
    random.shuffle(r)
    return r


def update_progress(num_processed, num_all_files, num_pending, t0, active_count=0):
    """Update progress bar on a single line"""
    now = time.monotonic() - t0
    perc_done = num_processed / num_all_files * 100 if num_all_files > 0 else 0

    # Calculate ETA
    if num_processed > 0:
        est_time_left = (now / num_processed * num_all_files) - now
        eta_min = int(est_time_left // 60)
        eta_sec = int(est_time_left % 60)
        eta_str = f"{eta_min}m{eta_sec:02d}s"
    else:
        eta_str = "calculating..."

    # Format elapsed time
    elapsed_min = int(now // 60)
    elapsed_sec = int(now % 60)
    elapsed_str = f"{elapsed_min}m{elapsed_sec:02d}s"

    # Create progress bar
    bar_length = 30
    filled_length = int(bar_length * perc_done / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    # Format the progress line
    status = f"\r[{bar}] {num_processed}/{num_all_files} ({perc_done:.1f}%) | Threads: {active_count} | Pending: {num_pending} | ETA: {eta_str} | Elapsed: {elapsed_str}"

    # Acquire lock to prevent output garbling
    with print_lock:
        sys.stdout.write(status)
        sys.stdout.flush()


def process_files_in_threads(file_list: list[str], thread_count=40, chunk_size=100):
    """
    Processes a list of files using a specified number of threads, each handling a chunk of files.

    :param file_list: List of input file names.
    :param thread_count: Number of threads to use.
    :param chunk_size: Number of files each thread should handle in a single batch.
    """
    file_list_lock = Lock()

    file_list0 = file_list
    file_list = missing_files(file_list)
    num_processed = 0
    num_all_files = len(file_list)
    active_threads = 0
    active_lock = Lock()

    t0 = time.monotonic()

    print(f"Total files to process: {num_all_files}")

    if not file_list:
        print("All files processed already.")
        return

    thread_count = min(thread_count, len(file_list))
    print(f"Using {thread_count} threads with chunk size {chunk_size}")

    # Initialize progress display
    update_progress(0, num_all_files, len(file_list), t0, 0)

    def worker():
        nonlocal file_list, num_processed, active_threads

        with active_lock:
            active_threads += 1

        try:
            while True:
                files_chunk = []
                with file_list_lock:
                    if not file_list:
                        # Check for any remaining files
                        file_list = missing_files(file_list0)
                    if not file_list:
                        # No more files to process
                        break

                    # Take a chunk of files
                    chunk = min(chunk_size, (len(file_list) // thread_count) + 20)
                    files_chunk = file_list[:chunk]
                    del file_list[:chunk]

                # Process this chunk of files
                run_cmd(files_chunk)

                # Check which files were actually processed
                unprocessed_files = missing_files(files_chunk)
                processed_here = len(files_chunk) - len(unprocessed_files)

                # Update counters and progress
                with file_list_lock:
                    num_processed += processed_here
                    file_list.extend(unprocessed_files)
                    num_pending = len(file_list)
                    random.shuffle(file_list)

                # Update progress display
                update_progress(num_processed, num_all_files, num_pending, t0, active_threads)
        finally:
            with active_lock:
                active_threads -= 1

    # Start worker threads
    threads = []
    for _ in range(thread_count):
        thread = threading.Thread(target=worker)
        thread.daemon = True
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Final newline after progress bar
    print()
    total_time = time.monotonic() - t0
    print(f"Completed processing {num_processed}/{num_all_files} files in {total_time:.2f}s")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    from src.maskbench.src.runner import setup_argparse, get_output, get_files, get_engine

    parser = setup_argparse()
    args = parser.parse_args()

    engine = get_engine(args)
    output_path = get_output(args)

    file_list = get_files(args)
    if not file_list:
        raise Exception("No files found")

    args_to_pass = [a for a in sys.argv[1:] if a not in args.files]
    cmd += args_to_pass

    # Print information about source glob patterns
    src_paths = ", ".join(args.files)
    print(f"Expanded '{src_paths}' to {len(file_list)} JSON files", file=sys.stderr)
    
    info = f"{len(file_list)} files, timeout {args.time_limit}s, memory {args.mem_limit}GB, "
    info += f"output {output_path}; {args.num_threads} threads; chunk size {args.chunk_size}; cmd: {' '.join(cmd)}"

    print(info, file=sys.stderr)

    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "meta.txt"), "w") as meta:
        meta.write(
            json.dumps(
                {
                    "id": engine.get_id(),
                    "name": engine.get_name(),
                    "module": engine.get_module(),
                    "module_version": engine.get_version(),
                    "cmd": cmd,
                    "info": info,
                },
                indent=2,
            )
        )

    process_files_in_threads(file_list, thread_count=args.num_threads, chunk_size=args.chunk_size)
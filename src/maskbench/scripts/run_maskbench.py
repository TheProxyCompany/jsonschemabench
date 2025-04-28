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

    # Ensure num_processed doesn't exceed num_all_files for percentage calculation
    effective_processed = min(num_processed, num_all_files)
    perc_done = (effective_processed / num_all_files * 100) if num_all_files > 0 else 0

    # Format time in a human-readable way
    def format_time(seconds):
        if seconds < 0:
            return "0s"
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    # Calculate ETA with safeguards
    if effective_processed > 0 and effective_processed < num_all_files:
        # Calculate time per file and multiply by remaining files
        time_per_file = now / effective_processed
        remaining_files = num_all_files - effective_processed
        est_time_left = time_per_file * remaining_files
        eta_str = format_time(est_time_left)
    elif effective_processed >= num_all_files:
        eta_str = "complete"
    else:
        eta_str = "calculating..."

    # Format elapsed time
    elapsed_str = format_time(now)

    # Create progress bar with bounds checking
    bar_length = 30
    filled_length = min(bar_length, int(bar_length * perc_done / 100))
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    # Format the progress line with ample padding
    status = f"\r[{bar}] {effective_processed}/{num_all_files} ({min(perc_done, 100.0):.1f}%) | Threads: {active_count} | Pending: {num_pending} | ETA: {eta_str:<13} | Elapsed: {elapsed_str}"
    
    # Add sufficient padding to ensure cursor is away from text and ANSI escape to hide cursor
    status += " " * 20 + "\033[?25l"
    
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

    # Final newline after progress bar and restore cursor visibility
    with print_lock:
        sys.stdout.write("\r\033[?25h\n")  # Show cursor and move to next line
        sys.stdout.flush()
    
    total_time = time.monotonic() - t0

    # Use the same formatting function for consistency
    def format_time(seconds):
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    formatted_time = format_time(total_time)
    print(f"Completed processing {num_processed}/{num_all_files} files in {formatted_time}")


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

    try:
        process_files_in_threads(file_list, thread_count=args.num_threads, chunk_size=args.chunk_size)
    except KeyboardInterrupt:
        # Make sure cursor is visible if user interrupts
        sys.stdout.write("\r\033[?25h\n")
        sys.stdout.flush()
        print("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        # Make sure cursor is visible on error
        sys.stdout.write("\r\033[?25h\n")
        sys.stdout.flush()
        print(f"Error: {e}")
        raise

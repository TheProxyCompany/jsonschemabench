"""
Orchestrates running the maskbench runner script on multiple files using threading.

This script manages a pool of worker threads to process a list of input files
by invoking the `src.maskbench.runner` module as a subprocess for each chunk of files.
It handles logging, progress reporting, and checking for completed files based on
the existence of corresponding output files.
"""

import subprocess
import os
import threading
from threading import Lock
import random
import sys
import json
import time

# Base command for invoking the runner module
# Note: This assumes the script is run from the project root containing the 'src' directory.
BASE_CMD = ["python", "-m", "src.maskbench.runner"]
LOG_LOCK = Lock()


def append_to_log(entry: str, output_path: str):
    """Appends a log entry to the log file in the specified output directory."""
    log_file = os.path.join(output_path, "log.txt")
    # Ensure the output directory exists; suppress errors if it already exists.
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    # Use a lock to prevent race conditions during file writing from multiple threads.
    with LOG_LOCK:
        # Open in append mode ('a')
        with open(log_file, "a", encoding="utf-8") as log:
            log.write(entry + "\n")


def run_cmd(file_list: list[str], base_cmd: list[str], output_path: str) -> bool:
    """
    Runs the runner command as a subprocess for a list of files.

    Constructs the full command, executes it with the project root as the
    working directory, logs the output, and returns True if the subprocess
    exited with code 0, False otherwise.

    Args:
        file_list: List of input files for this subprocess run.
        base_cmd: The base command list (e.g., ['python', '-m', 'src.maskbench.runner', '--arg']).
        output_path: Path to the output directory for logging.

    Returns:
        True if the subprocess ran successfully (exit code 0), False otherwise.
    """
    command = base_cmd + file_list
    # Use repr for safer logging of command parts, especially paths
    log_entry = f"Running command: {' '.join(map(repr, command))}\n"
    success = False
    # Assume script is in src/maskbench/scripts, project root is 3 levels up.
    app_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # Interpret stdout/stderr as text
            check=False,  # Don't raise exception on non-zero exit code
            cwd=app_root,  # Run from project root for correct module resolution
            encoding="utf-8",  # Specify encoding
            errors="replace",  # Handle potential encoding errors in output
        )
        log_entry += f"cwd: {app_root}\n"
        # Ensure stderr/stdout are strings before appending
        stderr_str = result.stderr if result.stderr else ""
        stdout_str = result.stdout if result.stdout else ""
        log_entry += f"{stderr_str}{stdout_str}\nExit code: {result.returncode}\n"
        success = result.returncode == 0
    except FileNotFoundError:
        # Handle case where python or the module path is wrong
        log_entry += "Error: Command not found. Check BASE_CMD and Python path.\n"
        success = False
    except Exception as e:
        # Catch other potential exceptions during subprocess execution
        log_entry += f"Error running command: {e}\n"
        success = False

    append_to_log(log_entry, output_path)
    return success


def missing_files(file_list: list[str], output_path: str) -> list[str]:
    """
    Checks a list of input files and returns those whose corresponding output
    file (basename match) does not exist in the output directory.
    """
    missing = [
        f
        for f in file_list
        if not os.path.exists(os.path.join(output_path, os.path.basename(f)))
    ]
    # Shuffle to potentially distribute work better if retrying
    random.shuffle(missing)
    return missing


def process_files_in_threads(
    initial_file_list: list[str],
    base_cmd: list[str],
    output_path: str,
    thread_count: int = 40,
    chunk_size: int = 100,
):
    """
    Processes a list of files using worker threads invoking the runner subprocess.

    Manages a queue of files, distributes chunks to worker threads,
    tracks progress, and handles retrying failed files.

    Args:
        initial_file_list: Complete list of input files to process.
        base_cmd: The base command list passed to `run_cmd`.
        output_path: Path to the output directory for results and logs.
        thread_count: Maximum number of worker threads to use.
        chunk_size: Target number of files for each thread to process per subprocess call.
    """
    file_list_lock = Lock()
    # Keep the original list for re-checking
    original_files = initial_file_list[:]
    # Start with files currently missing output
    files_to_process = missing_files(original_files, output_path)
    num_processed_successfully = 0
    num_initially_missing = len(files_to_process)

    t_start = time.monotonic()

    print(f"Target files to process: {num_initially_missing}")

    if not files_to_process:
        print("All target files already have corresponding output.")
        return

    # Adjust thread count if fewer files than threads
    actual_thread_count = min(thread_count, num_initially_missing)
    print(f"Using {actual_thread_count} threads.")

    def worker():
        # Make variables from outer scope available
        nonlocal files_to_process, num_processed_successfully

        while True:
            files_chunk = []
            # --- Critical section: Access shared file list ---
            with file_list_lock:
                if not files_to_process:
                    # Double check if any files are still missing output
                    # This handles cases where a file might fail transiently
                    files_to_process = missing_files(original_files, output_path)

                # If still no files, worker can exit
                if not files_to_process:
                    return  # Exit worker thread

                # Determine chunk size dynamically
                # Aim for roughly equal distribution, but respect chunk_size limit
                # Ensure at least one file is processed if list is not empty
                dynamic_chunk = max(
                    1,
                    (len(files_to_process) + actual_thread_count - 1)
                    // actual_thread_count,
                )
                current_chunk_size = min(
                    chunk_size, dynamic_chunk, len(files_to_process)
                )

                # Take a chunk of files from the shared list
                files_chunk = files_to_process[:current_chunk_size]
                del files_to_process[:current_chunk_size]
            # --- End Critical section ---

            if not files_chunk:
                # Should ideally not happen due to logic above, but acts as safeguard
                continue

            # Run the command for the selected chunk of files
            run_succeeded = run_cmd(files_chunk, base_cmd, output_path)

            processed_in_chunk = 0
            failed_in_chunk = []

            if run_succeeded:
                # If subprocess exit code was 0, check which output files were created
                failed_in_chunk = missing_files(files_chunk, output_path)
                processed_in_chunk = len(files_chunk) - len(failed_in_chunk)
            else:
                # If subprocess failed, assume all files in the chunk failed processing
                failed_in_chunk = files_chunk
                processed_in_chunk = 0
                # Consider adding a retry limit or specific handling for persistent failures

            # --- Critical section: Update progress and remaining files ---
            with file_list_lock:
                num_processed_successfully += processed_in_chunk
                # Add failed files back to the list for potential retry
                files_to_process.extend(failed_in_chunk)
                num_pending = len(files_to_process)
                # Shuffle if files were added back
                if failed_in_chunk:
                    random.shuffle(files_to_process)
            # --- End Critical section ---

            # --- Progress Reporting ---
            now = time.monotonic()
            elapsed_time = now - t_start
            # Avoid division by zero if nothing processed yet
            progress_perc = (
                (num_processed_successfully / num_initially_missing * 100)
                if num_initially_missing > 0
                else 100.0
            )
            # Estimate remaining time, handle division by zero
            est_remaining_sec = (
                (
                    (elapsed_time / (num_processed_successfully + 1e-9))
                    * (num_initially_missing - num_processed_successfully)
                )
                if num_processed_successfully < num_initially_missing
                else 0
            )

            print(
                f"{elapsed_time:.1f}s | OK: {processed_in_chunk}, Fail/Retry: {len(failed_in_chunk)} | "
                f"Pending: {num_pending} | Done: {progress_perc:.1f}% ({num_processed_successfully}/{num_initially_missing}) | "
                f"ETA: {est_remaining_sec:.1f}s",
                flush=True,  # Ensure progress prints timely
            )
            # --- End Progress Reporting ---

    # --- Start and manage worker threads ---
    threads = []
    for i in range(actual_thread_count):
        thread = threading.Thread(target=worker, name=f"Worker-{i + 1}")
        threads.append(thread)
        thread.start()

    # Wait for all worker threads to complete
    for thread in threads:
        thread.join()
    # --- End thread management ---

    # --- Final Summary ---
    t_end = time.monotonic()
    final_missing = missing_files(original_files, output_path)
    if final_missing:
        print(
            f"\nWarning: {len(final_missing)} files could not be processed successfully after {t_end - t_start:.2f}s."
        )
        # Optionally print some missing files here if needed for debugging
    else:
        print(
            f"\nAll {num_initially_missing} target files processed successfully in {t_end - t_start:.2f}s."
        )
    # --- End Final Summary ---


def main():
    """Parses arguments, prepares environment, and starts file processing."""
    # This script needs access to modules within the 'src' directory
    # Ensure the parent directory of 'src' is discoverable if running from elsewhere,
    # though running via `python -m src.maskbench` handles this.
    # sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..")) # Usually not needed if installed/run as module

    # Imports specific to maskbench runner setup
    try:
        from src.maskbench.src.runner import (
            setup_argparse,
            get_output,
            get_files,
            get_engine,
        )
    except ImportError:
        print(
            "Error: Could not import runner components. "
            "Ensure maskbench is installed correctly or PYTHONPATH is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Use the globally defined base command
    current_base_cmd = BASE_CMD[:]
    parser = setup_argparse()
    args = parser.parse_args()

    # --- Setup based on parsed arguments ---
    engine = get_engine(args)
    output_path = get_output(args)
    initial_file_list = get_files(args)

    if not initial_file_list:
        print(
            "Error: No input files found matching the provided arguments.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Construct the final base command by adding arguments passed to this script
    # Exclude the input file paths themselves from being passed as general args
    args_to_pass_to_runner = [arg for arg in sys.argv[1:] if arg not in args.files]
    current_base_cmd.extend(args_to_pass_to_runner)

    # --- Log Run Information ---
    info = (
        f"{len(initial_file_list)} files | "
        f"Timeout: {args.time_limit}s | Memory: {args.mem_limit}GB | "
        f"Output: {output_path} | Threads: {args.num_threads} | "
        f"ChunkSize: {args.chunk_size} | "  # Assuming chunk size arg exists or using default
        f"BaseCmd: {' '.join(map(repr, current_base_cmd))}"
    )

    print(info, file=sys.stderr)

    # Ensure output directory exists
    os.makedirs(output_path, exist_ok=True)

    # Write metadata about the run
    meta_file_path = os.path.join(output_path, "meta.txt")
    try:
        with open(meta_file_path, "w", encoding="utf-8") as meta:
            json.dump(
                {
                    "engine_id": engine.get_id(),
                    "engine_name": engine.get_name(),
                    "engine_module": engine.get_module(),
                    "engine_module_version": engine.get_version(),
                    "base_command": current_base_cmd,
                    "run_info": info,
                },
                meta,
                indent=2,
            )
    except IOError as e:
        print(f"Error writing meta file {meta_file_path}: {e}", file=sys.stderr)
        # Decide if this is critical enough to exit

    # --- Start Processing ---
    process_files_in_threads(
        initial_file_list=initial_file_list,
        base_cmd=current_base_cmd,
        output_path=output_path,
        thread_count=args.num_threads,
        chunk_size=args.chunk_size
        if hasattr(args, "chunk_size")
        else 100,  # Use arg or default
    )


if __name__ == "__main__":
    main()

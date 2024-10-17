#!/usr/bin/env python3

import os
import re
import subprocess
import sys
import time
from collections import deque

# Configuration
GIT_EXECUTABLE_PATH = os.environ.get("GIT_EXECUTABLE", "/usr/bin/git_orig")  # Path to the original git executable
SPEED_THRESHOLD = int(os.environ.get("GIT_FETCH_SPEED_THRESHOLD", 1000))  # Speed threshold in KiB/s
SPEED_WINDOW_SIZE = int(os.environ.get("GIT_FETCH_SPEED_WINDOW_SIZE", 5))  # Number of speed measurements to consider
SPEED_CHECK_INTERVAL = float(
    os.environ.get("GIT_FETCH_SPEED_CHECK_INTERVAL", 1)
)  # Interval between speed measurements in seconds
MAX_RETRIES = int(os.environ.get("GIT_FETCH_MAX_RETRIES", 5))  # Maximum number of retries
RETRY_DELAY = float(os.environ.get("GIT_FETCH_RETRY_DELAY", 1))  # Delay between retries in seconds
FETCH_TIMEOUT_BEFORE_SPEED_CHECK = float(
    os.environ.get("GIT_FETCH_TIMEOUT_BEFORE_SPEED_CHECK", 60)
)  # Timeout before speed is checked in seconds


def run_git_command(git_command: list[str]) -> int:
    """
    Runs the git command and monitors the speed. Retries if no speed is reported after the timeout.
    If unsuccessful after MAX_RETRIES, runs the command normally.

    Parameters
    ----------
    git_command : list[str]
        The git command to run as a list of strings.

    Returns
    -------
    int
        The return code of the git command.
    """
    retries = 0
    process = None

    while retries < MAX_RETRIES:
        speed_measurements: deque[int] = deque(maxlen=SPEED_WINDOW_SIZE)
        if retries > 0:
            print(
                f"\nAttempt {retries + 1}/{MAX_RETRIES}: Running command - {' '.join(git_command)}",
                file=sys.stderr,
            )

        process = subprocess.Popen(
            git_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )

        start_time = time.time()
        last_speed_check_time = start_time
        speed_reported = False

        try:
            for line in process.stdout:  # type: ignore
                sys.stdout.write(line)
                sys.stdout.flush()

                current_time = time.time()

                if current_time - start_time >= FETCH_TIMEOUT_BEFORE_SPEED_CHECK and not speed_reported:
                    print(
                        f"\nNo speed reported after {FETCH_TIMEOUT_BEFORE_SPEED_CHECK} seconds. Retrying...",
                        file=sys.stderr,
                    )
                    process.terminate()
                    process.wait()
                    break

                # extract from following format: Receiving objects: 62% (193/310), 14.37 MiB | 28.73 MiB/s
                speed_match = re.search(r"([0-9.]+) ([KMG])iB/s", line)
                if speed_match:
                    speed_reported = True
                    speed = float(speed_match.group(1))
                    unit = speed_match.group(2)
                    if unit == "M":
                        speed *= 1024
                    elif unit == "G":
                        speed *= 1024 * 1024
                    speed_measurements.append(int(speed))

                if current_time - last_speed_check_time >= SPEED_CHECK_INTERVAL:
                    if len(speed_measurements) == speed_measurements.maxlen:
                        avg_speed = sum(speed_measurements) / len(speed_measurements)
                        if avg_speed < SPEED_THRESHOLD:
                            print(
                                f"\nAverage speed ({avg_speed:.2f} KiB/s) below threshold. Retrying...",
                                file=sys.stderr,
                            )
                            process.terminate()
                            process.wait()
                            break

                    last_speed_check_time = current_time

            else:
                process.wait()
                if process.returncode == 0:
                    return 0

        except subprocess.SubprocessError as e:
            print(f"\nSubprocess error during git operation: {e}", file=sys.stderr)
        except Exception as e:
            print(f"\nUnexpected error during git operation: {e}", file=sys.stderr)

        retries += 1
        if retries < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    # If we've exhausted all retries, run the command normally
    print(f"\nExhausted all {MAX_RETRIES} retries. Running command normally.", file=sys.stderr)
    return subprocess.call(git_command)


def main():
    if not os.path.exists(GIT_EXECUTABLE_PATH):
        print(
            f"Error: The original git executable (specified in GIT_EXECUTABLE) not found at {GIT_EXECUTABLE_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    git_args = sys.argv[1:]

    if "fetch" in git_args:
        if "--progress" not in git_args:
            git_args.append("--progress")

        git_command = [GIT_EXECUTABLE_PATH] + git_args
        result = run_git_command(git_command)
    else:
        # For non-fetch commands, just forward to the original git
        git_command = [GIT_EXECUTABLE_PATH] + git_args
        result = subprocess.call(git_command)

    sys.exit(result)


if __name__ == "__main__":
    main()
import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO)

# List of allowed commands for validation
ALLOWED_COMMANDS = [["ruff", "format", "."], ["ruff", "check", "."], ["mypy", "src/"]]


def run_command(command):
    if command not in ALLOWED_COMMANDS:
        logging.error(f"Attempted to run an untrusted command: {' '.join(command)}")
        sys.exit(1)

    try:
        subprocess.run(command, check=True)  # noqa: S603
    except subprocess.CalledProcessError as e:
        logging.error(f"Command '{' '.join(command)}' failed with exit code {e.returncode}")
        sys.exit(e.returncode)


# Commands to run
commands = [["ruff", "format", "."], ["ruff", "check", "."], ["mypy", "src/"]]

# Execute each command
for command in commands:
    logging.info(f"Running: {' '.join(command)}")
    run_command(command)

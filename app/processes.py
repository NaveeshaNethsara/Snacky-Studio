"""Cancellable subprocesses for isolated extractors and bundled FFmpeg."""
import os
import subprocess
import time

from app.jobs import DownloadCancelled


def run_process(command, *, cancel=None, timeout=120, input_data=None, cwd=None):
    options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
               "cwd": cwd, "env": os.environ | {"PYTHONIOENCODING": "utf-8"}}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(command, **options)
    deadline = time.monotonic() + timeout
    pending_input = input_data
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("Media processing timed out. Please try again.")
            try:
                output, errors = process.communicate(input=pending_input, timeout=.2)
                return process.returncode, output, errors
            except subprocess.TimeoutExpired:
                pending_input = None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

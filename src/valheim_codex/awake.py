"""Temporary macOS idle-sleep prevention for an active gameplay test."""
import os
import subprocess
import sys


class Awake:
    def __init__(self):
        self.process = None
        if sys.platform == "darwin":
            self.process = subprocess.Popen(["/usr/bin/caffeinate", "-di", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

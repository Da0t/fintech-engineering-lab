"""Local-only Java process transport. Mutations are serialized per demo session."""
import atexit
import json
from pathlib import Path
import subprocess
import threading

ROOT = Path(__file__).resolve().parent


class MarketError(ValueError):
    pass


class Market:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        atexit.register(self.close)

    def start(self):
        source = ROOT / "java" / "MarketEngine.java"
        build = ROOT / "build"
        build.mkdir(exist_ok=True)
        target = build / "MarketEngine.class"
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(["javac", "-encoding", "UTF-8", "--release", "17", "-d", str(build), str(source)], check=True, capture_output=True, timeout=30)
        self.process = subprocess.Popen(["java", "-Dfile.encoding=UTF-8", "-cp", str(build), "MarketEngine"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

    def command(self, command):
        if "\n" in command or "\r" in command:
            raise MarketError("Invalid command delimiters")
        with self.lock:
            if self.process is None:
                self.start()
            if self.process.poll() is not None:
                raise MarketError("Java engine exited; restart the demo server to create a new session")
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise MarketError("Java engine stopped responding")
            result = json.loads(line)
            if "error" in result:
                raise MarketError(result["error"])
            return result

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process is not None:
            for stream in [self.process.stdin, self.process.stdout, self.process.stderr]:
                stream.close()

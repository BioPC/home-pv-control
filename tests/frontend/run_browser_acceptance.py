"""Linux CI supervision: exact child status, bounded owned-process cleanup."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def processes():
    result = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().split(") ", 1)[1].split()
            result[int(path.parent.name)] = {
                "parent": int(fields[1]),
                "started": fields[19],
                "state": fields[0],
            }
        except (OSError, IndexError, ValueError):
            continue  # Processes may exit while /proc is being enumerated.
    return result


def live_owned(owned):
    snapshot = processes()
    return [
        pid
        for pid, started in owned.items()
        if pid in snapshot
        and snapshot[pid]["started"] == started
        and snapshot[pid]["state"] != "Z"
    ]


def terminate_owned(owned):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in live_owned(owned):
            # Recheck creation time to avoid signalling a reused PID.
            if pid not in live_owned(owned):
                continue
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(1)
    return live_owned(owned)


def supervise(command, seconds, log_path):
    owned = {}
    started = time.monotonic()
    timed_out = False
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Child/driver stderr goes to a regular file, never an inherited tee pipe.
    with (
        log_path.open("wb") as log,
        log_path.open("r", encoding="utf-8", errors="replace") as reader,
    ):
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while True:
            snapshot = processes()
            roots = {child.pid} | set(live_owned(owned))
            changed = True
            while changed:
                changed = False
                for pid, row in snapshot.items():
                    if pid in roots or row["parent"] in roots:
                        if pid not in roots:
                            roots.add(pid)
                            changed = True
                        owned.setdefault(pid, row["started"])
            print(reader.read(), end="", flush=True)
            if child.poll() is not None:
                break
            if time.monotonic() - started > seconds:
                timed_out = True
                terminate_owned(owned)
                break
            time.sleep(0.25)
        # Allow normal browser/driver shutdown; never leave a live owned child.
        deadline = time.monotonic() + 2
        while live_owned(owned) and time.monotonic() < deadline:
            time.sleep(0.1)
        leaked = live_owned(owned)
        remaining = terminate_owned(owned) if leaked else []
        child.wait(timeout=5)
        print(reader.read(), end="", flush=True)
    code = 124 if timed_out else child.returncode
    if code < 0:
        code = 128 - code
    if code == 0 and (leaked or remaining):
        code = 1
    return {
        "exit_code": code,
        "pytest_exit_code": child.returncode,
        "timed_out": timed_out,
        "leaked_owned_processes": leaked,
        "remaining_owned_processes": remaining,
        "elapsed_seconds": time.monotonic() - started,
    }


def main():
    if not Path("/proc/self/stat").exists():
        raise SystemExit("This supervisor requires the isolated Linux CI runner.")
    probes = Path("work/frontend-supervisor-probes")
    status = supervise(
        [sys.executable, "-c", "print('exit-status probe');raise SystemExit(23)"],
        10,
        probes / "exit.log",
    )
    assert status["exit_code"] == 23 and not status["remaining_owned_processes"], status
    status = supervise(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);time.sleep(60)",
        ],
        2,
        probes / "timeout.log",
    )
    assert status["exit_code"] == 124 and not status["remaining_owned_processes"], (
        status
    )
    print(
        "SUPERVISOR_PROBES_PASS: Python exit 23 preserved; timed-out descendant tree terminated",
        flush=True,
    )
    command = [
        sys.executable,
        "-u",
        "-m",
        "pytest",
        "tests/frontend",
        "-v",
        "-ra",
        "-s",
        "-o",
        "faulthandler_timeout=240",
        "--junitxml=frontend-results.xml",
    ]
    status = supervise(command, 600, Path("frontend-browser.log"))
    Path("frontend-runner-status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(status), flush=True)
    raise SystemExit(status["exit_code"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Kimi-only, native-auth relay; cwd/skills reduction, NOT an OS sandbox.

Requires POSIX process groups and waitid(WNOWAIT). Keep the child leader owned
and UNREAPED until group cancellation finishes, including normal exit. Never
poll()/wait()/communicate() before killpg: those may free the leader's PID.
Inherited HOME/config/env remain intentional; only the CLI owns native auth.
"""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


def non_git(path):
    """Check physical ancestors, independent of inherited Git discovery settings."""
    for parent in (path, *path.parents):
        if os.path.lexists(parent / '.git') or (
            (parent / 'HEAD').exists() and (parent / 'objects').is_dir() and (parent / 'refs').is_dir()
        ):
            return False
    return True


def cancel_owned_group(proc):
    """TERM then KILL before reaping; an exited zombie still pins its PID/PGID."""
    # This function is called exactly once, and no other code reaps this child.
    if os.getpgid(proc.pid) != proc.pid:
        raise RuntimeError('Kimi leader no longer owns its process group')
    os.killpg(proc.pid, signal.SIGTERM)
    time.sleep(.2)
    # Do not wait/poll in the grace period: TERM can exit the leader while a
    # descendant ignores it. The unreaped leader prevents PGID reuse here.
    if os.getpgid(proc.pid) != proc.pid:
        raise RuntimeError('Kimi process-group ownership changed')
    os.killpg(proc.pid, signal.SIGKILL)
    return proc.wait()


def main():
    args = sys.argv[1:]
    if not 1 <= len(args) <= 3:
        print('kimi-relay: usage: PROMPT [MODEL] [text|stream-json]', file=sys.stderr)
        return 2
    prompt = args[0]
    model = (args[1] if len(args) > 1 else '') or os.environ.get('HEADLESS_RELAY_KIMI_MODEL') or 'kimi-code/k3'
    output = (args[2] if len(args) > 2 else '') or 'text'
    limit = os.environ.get('HEADLESS_RELAY_KIMI_TIMEOUT_SECONDS', '600')
    if output not in ('text', 'stream-json') or not re.fullmatch(r'[0-9]+', limit) or len(limit) > 9 or int(limit) == 0:
        print('kimi-relay: invalid format or positive-integer timeout', file=sys.stderr)
        return 2
    if os.name != 'posix' or not all(hasattr(os, name) for name in ('waitid', 'WNOWAIT', 'WEXITED', 'WNOHANG', 'P_PID')):
        print('kimi-relay: POSIX waitid(WNOWAIT) required; refusing', file=sys.stderr)
        return 1
    stopped = 0

    def on_signal(signum, _frame):
        nonlocal stopped
        stopped = stopped or signum

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, on_signal)
    # Resolve BEFORE the child's cwd changes; honour relative TMPDIR explicitly.
    temp_root = Path(os.environ.get('TMPDIR') or tempfile.gettempdir()).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='kimi-iso.', dir=str(temp_root)) as temp:
        cwd = Path(temp).resolve(strict=True)
        if not non_git(cwd):
            print('kimi-relay: temporary cwd is inside a git repository; refusing', file=sys.stderr)
            return 1
        skills = cwd / 'skills'
        skills.mkdir(mode=0o700)
        if stopped:
            return 128 + stopped
        proc = subprocess.Popen(['kimi', '--skills-dir', str(skills), '-m', model,
                                 '-p', prompt, '--output-format', output], cwd=str(cwd),
                                stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + int(limit)
        result = None
        try:
            while True:
                if stopped:
                    result = 128 + stopped
                    break
                # Observe exit without reaping the leader (and freeing its PID).
                exited = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    break
                if time.monotonic() >= deadline:
                    result = 124
                    break
                time.sleep(.02)
        finally:
            status = cancel_owned_group(proc)
        if result is not None:
            return result
        return status if status >= 0 else 128 - status


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print('kimi-relay: refusing: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)

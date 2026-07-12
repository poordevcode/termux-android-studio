#!/data/data/com.termux/files/usr/bin/python3
"""Persistent Shizuku bridge for Termux Studio.

Why this exists: apps like MT Manager request the Shizuku binder ONCE and hold it,
so they keep working even when HyperOS/MIUI freezes or kills the Shizuku *manager
app* (the server, uid 2000, keeps running). rish however spawns a fresh client per
command, and every fresh client needs the manager app alive to hand over a binder —
that's why plain `shizuku exec` intermittently dies with "Request timeout" while
MT Manager works fine.

This bridge is studio's equivalent of MT Manager's held binder: it opens ONE rish
session (`shizuku shell`) under a pty at startup — the only moment the manager app
must be reachable — and then serves shell commands over a UNIX socket for as long
as it lives. After that first handshake the Shizuku app can be frozen, swiped away
or force-stopped; commands keep running against the held binder.

Protocol (one request per connection):
  client -> "<command>\n"       (single line; may contain ';' etc.)
  bridge -> command output ...
  bridge -> "__RC <n>\n"        (remote exit code; last line)
The pty echo is disabled and the remote PS1/PS2 are cleared so output stays clean.

The bridge exits when the rish child dies (server stopped / binder revoked); the
studio CLI notices the dead socket and restarts the bridge (thawing the app first).
"""

import os
import pty
import re
import select
import signal
import socket
import sys
import termios
import time

DIR = os.path.expanduser("~/.studio/shizuku-daemon")
SOCK_PATH = os.path.join(DIR, "bridge.sock")
PID_PATH = os.path.join(DIR, "bridge.pid")
LOG_PATH = os.path.join(DIR, "bridge.log")

STARTUP_TIMEOUT = 25       # s to wait for the first rish handshake
CMD_TIMEOUT = 300          # s hard cap per command (client usually times out sooner)


def log(msg):
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


def spawn_rish():
    """Start `shizuku shell` under a pty; returns (pid, master_fd)."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("shizuku", ["shizuku", "shell"])
        os._exit(127)
    # Kill input echo so command output isn't polluted with our own writes.
    try:
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except termios.error:
        pass
    return pid, fd


def read_until(fd, pattern, deadline):
    """Read the pty until `pattern` (compiled re, matched per line) or deadline.
    Returns (matched_line_match, collected_text_before_match) — match None on
    timeout/EOF."""
    buf = b""
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.25)
        if not r:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return None, buf.decode("utf-8", "replace")
        if not chunk:
            return None, buf.decode("utf-8", "replace")
        buf += chunk
        text = buf.decode("utf-8", "replace")
        for line in text.splitlines():
            m = pattern.match(line.strip())
            if m:
                before = text[: text.find(line)]
                return m, before
    return None, buf.decode("utf-8", "replace")


def main():
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    try:
        os.unlink(SOCK_PATH)
    except OSError:
        pass

    pid, fd = spawn_rish()
    log("rish spawned pid=%d" % pid)

    # First handshake: this is the ONLY step that needs the Shizuku app reachable.
    # rish prints its banner, and on failure "Request timeout ..." then exits.
    # Input written before the remote shell is ready gets dropped, so re-send the
    # ready-probe every couple of seconds until it echoes back.
    nonce = "%d" % os.getpid()
    ready = re.compile(r"^__READY_%s$" % nonce)
    deadline = time.time() + STARTUP_TIMEOUT
    m, out = None, ""
    while m is None and time.time() < deadline:
        try:
            # stty -echo must run REMOTELY: rish allocates a device-side pty and
            # that line discipline (not our local master) echoes our input back.
            os.write(fd, ("stty -echo 2>/dev/null; PS1=''; PS2=''; "
                          "echo __READY_%s\n" % nonce).encode())
        except OSError:
            break
        m, out = read_until(fd, ready, min(time.time() + 2.5, deadline))
    if not m:
        log("handshake failed: %r" % out[-300:])
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        sys.exit(1)
    log("handshake ok — binder held")

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o600)
    srv.listen(4)
    with open(PID_PATH, "w") as fh:
        fh.write(str(os.getpid()))

    seq = 0
    while True:
        # Serve until the rish child dies; then exit so the CLI can restart us.
        try:
            os.kill(pid, 0)
        except OSError:
            log("rish child gone — exiting")
            break
        srv.settimeout(5)
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            conn.settimeout(10)
            data = b""
            while not data.endswith(b"\n") and len(data) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            cmd = data.decode("utf-8", "replace").strip()
            if not cmd:
                conn.sendall(b"__RC 2\n")
                continue
            seq += 1
            sent = "%d_%d" % (os.getpid(), seq)
            # Group the command so 'cd x; y' etc. behave; sentinel carries its rc.
            os.write(fd, ("{ %s\n}; echo __SENT_%s_$?\n" % (cmd, sent)).encode())
            pat = re.compile(r"^__SENT_%s_(\d+)$" % sent)
            m, out = read_until(fd, pat, time.time() + CMD_TIMEOUT)
            # Drop prompt/control noise and any echoed copies of our own writes
            # (the remote pty echoes input despite stty -echo; the echoed first
            # line is exactly "{ <cmd>").
            echoed = ("{ " + cmd).strip()
            clean = "\n".join(
                l for l in out.splitlines()
                if l.strip() and "__SENT_" not in l and "__READY_" not in l
                and l.strip() != echoed
            )
            rc = m.group(1) if m else "255"
            payload = (clean + "\n" if clean else "") + "__RC %s\n" % rc
            conn.sendall(payload.encode())
            if not m:
                log("command timed out/EOF: %r" % cmd[:120])
        except (OSError, socket.timeout) as e:
            log("client error: %s" % e)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    try:
        os.unlink(SOCK_PATH)
    except OSError:
        pass
    try:
        os.unlink(PID_PATH)
    except OSError:
        pass
    sys.exit(1)


if __name__ == "__main__":
    main()

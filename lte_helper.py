# SPDX-License-Identifier: AGPL-3.0-only
"""Resident root helper. Only the current console user may request LTE on/off.

No client supplied paths, arguments, executable names or shell commands are used.
The socket and all executable/configuration parents are administrator owned.
"""
import ctypes
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import time
import lte_auto as auto

BASE = Path(__file__).resolve().parent
SOCKET = BASE/'control.sock'
PREFERENCE = BASE/'preferences.json'
STATE = BASE/'helper-state.json'
STOP = False


def atomic_json(path, value, mode=0o644):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(mode)
    temporary.replace(path)


def console_uid():
    return Path('/dev/console').stat().st_uid


def peer_uid(connection):
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    if libc.getpeereid(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)):
        raise OSError(ctypes.get_errno(), 'getpeereid')
    return uid.value


def read_preference():
    if not PREFERENCE.exists():
        return True  # migrate the previously installed, enabled service
    data = json.loads(PREFERENCE.read_text())
    if type(data.get('enabled')) is not bool:
        raise ValueError('Invalid root-owned LTE preference')
    return data['enabled']


def accept_command(connection, enabled):
    """Acknowledge only after the administrator-owned preference is committed."""
    connection.settimeout(0.25)
    uid = peer_uid(connection)
    if uid != 0 and (uid < 501 or uid != console_uid()):
        connection.sendall(b'DENIED\n')
        return enabled
    data = b''
    while len(data) < 3 and not data.endswith(b'\n'):
        part = connection.recv(3-len(data))
        if not part:
            break
        data += part
    if data not in (b'E\n', b'D\n'):
        connection.sendall(b'INVALID\n')
        return enabled
    desired = data == b'E\n'
    atomic_json(PREFERENCE, {'enabled': desired}, 0o600)
    connection.sendall(b'OK\n')
    return desired


def request(enabled):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(SOCKET))
        if peer_uid(client) != 0:
            raise PermissionError('LTE helper must be owned by root')
        client.sendall(b'E\n' if enabled else b'D\n')
        if client.recv(32) != b'OK\n':
            raise RuntimeError('LTE helper rejected request')


def stop_signal(signum, frame):
    global STOP
    STOP = True


def run():
    global STOP
    STOP = False
    if os.geteuid() != 0:
        raise PermissionError('Helper requires administrator installation')
    # Never execute code from a writable installation directory.
    for path in (BASE, BASE/'lte_auto.py', BASE/'lte_helper.py',
                 BASE/'failover_policy.py', BASE/'magicbay_lte_managed'):
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Unsafe helper installation: '+str(path))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop_signal)
    enabled = read_preference()
    enabled_at = datetime.now(timezone.utc).isoformat()
    child = None
    stopping_pid = None
    retry_at = 0
    error = None
    with Path('/var/run/magicbay-lte-helper.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if SOCKET.exists():
            if not stat.S_ISSOCK(SOCKET.lstat().st_mode):
                raise RuntimeError('Unexpected object at control socket')
            SOCKET.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            old_mask = os.umask(0o077)
            try:
                server.bind(str(SOCKET))
            finally:
                os.umask(old_mask)
            server.listen(4)
            server.settimeout(0.5)
            try:
                while not STOP:
                    os.chown(SOCKET, console_uid(), -1)
                    os.chmod(SOCKET, 0o600)
                    if child is not None and child.poll() is not None:
                        child = None
                        retry_at = time.monotonic()+10
                    live = auto.alive()
                    orphan = auto.orphan_engine() if not live else None
                    if not enabled and live and stopping_pid != live['pid']:
                        os.kill(live['pid'], signal.SIGUSR1)
                        stopping_pid = live['pid']
                    if not live and not orphan:
                        stopping_pid = None
                    if enabled and not live and not orphan and child is None and time.monotonic() >= retry_at:
                        child = subprocess.Popen(['/usr/bin/python3', str(BASE/'lte_auto.py'), 'run'],
                            cwd=str(BASE), close_fds=True)
                        retry_at = time.monotonic()+10
                        error = None
                    phase = ('stopping' if stopping_pid or (not enabled and (live or orphan or child)) else
                             'disabled' if not enabled else
                             'starting' if not live else 'enabled')
                    atomic_json(STATE, {'pid': os.getpid(), 'enabled': enabled, 'phase': phase,
                        'enabled_utc': enabled_at, 'updated_utc': datetime.now(timezone.utc).isoformat(),
                        'error': error, 'protocol_version': 1})
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        try:
                            desired = accept_command(connection, enabled)
                            if desired != enabled:
                                enabled_at = datetime.now(timezone.utc).isoformat()
                                retry_at = 0
                            enabled = desired
                        except (OSError, ValueError) as failure:
                            # Recover a persisted request even if a client disconnected before ACK.
                            enabled = read_preference()
                            auto.log('LTE control request not acknowledged: '+str(failure))
            finally:
                live = auto.alive()
                if live:
                    os.kill(live['pid'], signal.SIGUSR1)
                if child is not None and child.poll() is None and (not live or live['pid']!=child.pid):
                    child.send_signal(signal.SIGUSR1)
                deadline = time.monotonic()+40
                while (auto.alive() or auto.orphan_engine() or
                       (child is not None and child.poll() is None)) and time.monotonic() < deadline:
                    time.sleep(0.25)
                if child is not None:
                    child.poll()
                SOCKET.unlink(missing_ok=True)
                atomic_json(STATE, {'pid': os.getpid(), 'enabled': enabled, 'phase': 'offline',
                    'updated_utc': datetime.now(timezone.utc).isoformat(), 'protocol_version': 1})


if __name__ == '__main__':
    run()

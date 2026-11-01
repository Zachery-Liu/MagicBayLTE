# SPDX-License-Identifier: AGPL-3.0-only
"""Root-owned diagnostic files; read-only access for the active console user."""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess

STATE_FILES = ('auto-state.json', 'helper-state.json', 'modem-state.json',
               'auto-state.new', 'helper-state.new', 'modem-state.new', 'modem-state.json.new')


def checked(path, directory=False):
    info = Path(path).lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or info.st_uid != os.geteuid() or (not directory and info.st_nlink != 1):
        raise PermissionError('Unsafe local file: ' + str(path))


def chmod(*args):
    subprocess.run(['/bin/chmod', *map(str, args)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def reader_name(uid):
    # chmod's ACL parser expects a directory-service identity, not a numeric UID.
    return pwd.getpwuid(uid).pw_name if uid >= 501 else None


def file_access(path, reader):
    checked(path)
    path.chmod(0o600)
    chmod('-N', path)
    if reader:
        chmod('+a', 'user:' + reader + ' allow read,readattr,readextattr,readsecurity', path)


def configure(base, uid):
    """Called before launch, and whenever the console user changes. Never grant write."""
    base = Path(base)
    checked(base, directory=True)
    reader = reader_name(uid)
    chmod('-N', base)
    if reader:
        # Newly created atomic state files inherit only read access.
        chmod('+a', 'user:' + reader +
              ' allow read,readattr,readextattr,readsecurity,file_inherit,only_inherit', base)
    logs = base / 'logs'
    logs.mkdir(mode=0o700, exist_ok=True)
    checked(logs, directory=True)
    logs.chmod(0o700)
    chmod('-N', logs)
    if reader:
        chmod('+a', 'user:' + reader + ' allow list,search,readattr,readextattr,readsecurity', logs)
        chmod('+a', 'user:' + reader +
              ' allow read,readattr,readextattr,readsecurity,file_inherit,only_inherit', logs)
    for path in logs.iterdir():
        file_access(path, reader)
    for name in STATE_FILES:
        path = base / name
        try:
            file_access(path, reader)
        except FileNotFoundError:
            pass  # An atomic writer may have just renamed the temporary file.
    preference = base / 'preferences.json'
    if preference.exists() or preference.is_symlink():
        file_access(preference, None)


def private_output(path):
    """Create with 0600 from the outset; preserve an inherited read-only ACL."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise PermissionError('Unsafe output file: ' + str(path))
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        return os.fdopen(fd, 'w')
    except BaseException:
        os.close(fd)
        raise


def write_json(path, value, private=False):
    path = Path(path)
    temporary = path.with_suffix('.new')
    with private_output(temporary) as stream:
        if private:
            chmod('-N', temporary)  # Preferences must not inherit console read access.
        json.dump(value, stream, ensure_ascii=False, indent=2)
        if private:
            stream.flush()
            os.fsync(stream.fileno())
    temporary.replace(path)

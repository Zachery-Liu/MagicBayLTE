# SPDX-License-Identifier: AGPL-3.0-only
"""Build the pinned, unmodified libusb source archive without network access."""
from pathlib import Path
import hashlib
import os
import platform
import subprocess
import tarfile

BASE = Path(__file__).resolve().parents[1]
SHA256 = '5977fc950f8d1395ccea9bd48c06b3f808fd3c2c961b44b0c2e6e29fc3a70a85'


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64':
        raise SystemExit('This release builds on Intel macOS only; Apple Silicon is not validated.')
    archive = BASE / 'third_party/libusb-1.0.29.tar.bz2'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('libusb archive checksum mismatch')
    source = BASE / 'libusb-1.0.29'
    if not source.exists():
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if not parts or parts[0] != source.name or '..' in parts or member.issym() or member.islnk():
                    raise SystemExit('Unsafe dependency archive entry')
            tar.extractall(BASE)
    stamp = source / '.magicbay-build-flags'
    flags = '-O2 -arch x86_64 -mmacosx-version-min=13.0'
    if not stamp.exists() or stamp.read_text() != flags:
        env = dict(os.environ, CFLAGS=flags, MACOSX_DEPLOYMENT_TARGET='13.0')
        subprocess.run(['./configure', '--disable-shared', '--enable-static', '--disable-examples-build',
                        '--disable-tests-build'], cwd=source, env=env, check=True)
        subprocess.run(['/usr/bin/make', '-j2'], cwd=source, env=env, check=True)
        stamp.write_text(flags)
    if not (source / 'libusb/.libs/libusb-1.0.a').exists():
        raise SystemExit('libusb static library missing; remove the build stamp and rebuild')
    print('PASS: pinned libusb 1.0.29, x86_64, macOS deployment target 13.0')


if __name__ == '__main__':
    main()

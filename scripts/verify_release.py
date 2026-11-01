# SPDX-License-Identifier: AGPL-3.0-only
"""Expand and inspect a package without installing or executing its scripts."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from package_release import VERSION

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / 'dist')
    out = parser.parse_args(argv).output.resolve()
    for line in (out / 'SHA256SUMS.txt').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert Path(name).name == name
        assert sha(out / name) == expected, 'Release checksum mismatch: ' + name
    package = out / ('MagicBayLTE-'+VERSION+'-macOS-Intel.pkg')
    with tempfile.TemporaryDirectory(prefix='magicbay-inspect-') as directory:
        work = Path(directory)
        subprocess.run(['/usr/sbin/pkgutil', '--expand-full', str(package), str(work / 'expanded')], check=True)
        payloads = list((work / 'expanded').glob('*.pkg/Payload'))
        assert len(payloads) == 1, 'Unexpected component inventory'
        payload = payloads[0]
        target = payload / 'Library/Application Support/MagicBayLTE'
        assert not (target / 'preferences.json').exists(), 'Package must preserve existing intent'
        assert not list(target.glob('*-state.json')), 'Private state in package'
        app = payload / 'Applications/Magic Bay LTE.app'
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True)
        legal = app / 'Contents/Resources/Licenses'
        for name, source_name in (('AGPL-3.0.txt', 'LICENSE'), ('NOTICE.txt', 'NOTICE'),
                                 ('MIT-cellular.txt', 'LICENSE-cellular.txt'),
                                 ('LGPL-2.1.txt', 'LGPL-2.1.txt'), ('MIT-Octicons.txt', 'LICENSE-Octicons.txt')):
            assert sha(legal / name) == sha(target / 'Source' / source_name), 'Bundled legal notice mismatch'
        runtime = json.loads((target / 'installed-build.json').read_text())
        for name, expected in runtime['sha256'].items():
            assert sha(target / name) == expected, 'Payload hash mismatch: ' + name
        source = target / ('Source/MagicBayLTE-'+VERSION+'-source.tar.gz')
        assert sha(source) == sha(out / source.name), 'Embedded source differs'
        with tarfile.open(source) as tar:
            names = tar.getnames()
            assert not any('/.git/' in name or '/evidence/' in name or '/logs/' in name or
                           name.endswith('-state.json') for name in names), 'Private artifact in source'
            manifests = [name for name in names if name.endswith('/SOURCE_MANIFEST.json')]
            assert len(manifests) == 1
            manifest = json.load(tar.extractfile(manifests[0]))
            prefix = manifests[0].rsplit('/', 1)[0] + '/'
            for name, expected in manifest['source_sha256'].items():
                assert hashlib.sha256(tar.extractfile(prefix + name).read()).hexdigest() == expected
            assert prefix + 'third_party/libusb-1.0.29.tar.bz2' in names
            assert prefix + 'LICENSE' in names
        assert manifest['binary_sha256'] == runtime['sha256']
        print('PASS: release hashes, package payload, app signature, runtime hashes, complete embedded source, no local states/logs')


if __name__ == '__main__':
    main()

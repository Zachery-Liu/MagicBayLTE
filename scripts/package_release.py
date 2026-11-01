# SPDX-License-Identifier: AGPL-3.0-only
"""Package previously validated builds; never install or start an LTE service."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
VERSION = '1.4.2'
IDENTIFIER = 'io.github.zachery-liu.magicbaylte'
RUNTIME = ('lte_auto.py', 'failover_policy.py', 'magicbay_lte_managed',
           'lte_helper.py', 'network_events.py', 'magicbay_network_watch', 'lte_service.py')
RUNTIME_DIR = BASE / 'build/runtime'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_files():
    # Explicit source inventory prevents accidentally publishing local diagnostic
    # logs, private states, captures, caches, old app bundles or nested .git data.
    names = ['README.md', 'LICENSE', 'NOTICE', 'CHANGELOG.md',
             'CONTRIBUTING.md', '.gitignore', '.gitattributes']
    for pattern in ('backend/*.py', 'engine/*.h', 'engine/*.c', 'engine/*.py',
                    'tools/*.py', 'tests/*.py', 'tests/*.c', 'app/*.swift',
                    'app/*.h', 'app/*.c', 'app/*.py',
                    'app/Assets/*', 'scripts/*.py', 'packaging/scripts/*',
                    'packaging/*.py', 'docs/*.md', 'third_party/*', 'licenses/*',
                    'third_party/cellular/LICENSE', 'third_party/cellular/UPSTREAM.json',
                    'third_party/cellular/Sources/mbim_lte.c', '.github/workflows/*.yml'):
        names.extend(str(p.relative_to(BASE)) for p in BASE.glob(pattern) if p.is_file())
    return sorted(set(names))


def verify():
    backend = json.loads((BASE / 'build/validation/backend.json').read_text())
    if backend.get('offline_tests') != 'passed':
        raise RuntimeError('Offline validation has not passed')
    for name, sha in backend['sha256'].items():
        if digest(BASE / name) != sha:
            raise RuntimeError('Stale backend build: ' + name)
    app_manifest = json.loads((BASE / 'build/app/app-build.json').read_text())
    for name, sha in app_manifest['sha256'].items():
        if digest(BASE / 'app' / name) != sha:
            raise RuntimeError('Stale app build: ' + name)
    app = BASE / 'build/app/Magic Bay LTE.app'
    if digest(app / 'Contents/MacOS/Magic Bay LTE') != app_manifest['executable_sha256']:
        raise RuntimeError('App executable changed')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info['CFBundleShortVersionString'] != VERSION:
        raise RuntimeError('App and package versions differ')
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True)
    for name in public_files():
        path = BASE / name
        if path.is_symlink():
            raise RuntimeError('Symlink in public source: ' + name)
        if path.suffix != '.bz2' and (b'/' + b'Users/') in path.read_bytes():
            raise RuntimeError('Private user path in source: ' + name)
    return backend, app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / 'dist',
                        help='Output directory; use a separate path when validating an existing release version.')
    args = parser.parse_args(argv)
    backend, app = verify()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefix = 'MagicBayLTE-' + VERSION
    source = out / (prefix + '-source.tar.gz')
    inventory = {name: digest(BASE / name) for name in public_files()}
    with tempfile.TemporaryDirectory(prefix='magicbay-release-') as directory:
        work = Path(directory)
        source_root = work / prefix
        source_root.mkdir()
        for name in inventory:
            target = source_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / name, target)
            target.chmod(0o755 if name.startswith('packaging/scripts/') else 0o644)
        (source_root / 'SOURCE_MANIFEST.json').write_text(json.dumps({
            'version': VERSION, 'source_sha256': inventory,
            'binary_sha256': {name: digest(RUNTIME_DIR / name) for name in RUNTIME},
            'offline_tests': backend['offline_tests']}, indent=2) + '\n')
        with tarfile.open(source, 'w:gz') as tar:
            for path in sorted(source_root.rglob('*')):
                info = tar.gettarinfo(str(path), arcname=prefix + '/' + str(path.relative_to(source_root)))
                info.uid = info.gid = 0
                info.uname = info.gname = 'root'
                info.mtime = 0
                if path.is_file():
                    with path.open('rb') as stream:
                        tar.addfile(info, stream)
                else:
                    tar.addfile(info)
        payload = work / 'root'
        application = payload / 'Applications/Magic Bay LTE.app'
        application.parent.mkdir(parents=True)
        shutil.copytree(app, application)
        target = payload / 'Library/Application Support/MagicBayLTE'
        target.mkdir(parents=True)
        for name in RUNTIME:
            shutil.copyfile(RUNTIME_DIR / name, target / name)
            (target / name).chmod(0o755 if not name.endswith('.py') else 0o644)
        shutil.copyfile(BASE / 'packaging/uninstall.py', target / 'uninstall.py')
        (target / 'installed-build.json').write_text(json.dumps({
            'version': VERSION, 'offline_tests': 'passed',
            'sha256': {name: digest(RUNTIME_DIR / name) for name in RUNTIME}}, indent=2) + '\n')
        sources = target / 'Source'
        sources.mkdir()
        shutil.copyfile(source, sources / source.name)
        for name in ('LICENSE', 'NOTICE', 'README.md'):
            shutil.copyfile(BASE / name, sources / name)
        shutil.copyfile(BASE / 'third_party/cellular/LICENSE', sources / 'LICENSE-cellular.txt')
        shutil.copyfile(BASE / 'licenses/LGPL-2.1.txt', sources / 'LGPL-2.1.txt')
        shutil.copyfile(BASE / 'app/Assets/LICENSE-Octicons.txt', sources / 'LICENSE-Octicons.txt')
        daemon = payload / 'Library/LaunchDaemons/local.magicbay.lte.auto.plist'
        daemon.parent.mkdir(parents=True)
        # Importing the installer module only defines functions; it has no actions.
        import sys
        sys.path.insert(0, str(BASE / 'backend'))
        import lte_service
        daemon.write_bytes(plistlib.dumps(lte_service.definition()))
        scripts = work / 'scripts'
        shutil.copytree(BASE / 'packaging/scripts', scripts)
        for script in scripts.iterdir():
            script.chmod(0o755)
        # Explicit app component settings prevent relocation to an old bundle
        # elsewhere and prevent deleting unrelated files in the runtime directory.
        component = work / 'component.plist'
        component.write_bytes(plistlib.dumps([{'RootRelativeBundlePath': 'Applications/Magic Bay LTE.app',
            'BundleIsRelocatable': False, 'BundleIsVersionChecked': True,
            'BundleOverwriteAction': 'upgrade'}]))
        pkg = work / 'component.pkg'
        subprocess.run(['/usr/bin/pkgbuild', '--root', str(payload), '--scripts', str(scripts),
            '--component-plist', str(component), '--identifier', IDENTIFIER, '--version', VERSION,
            '--install-location', '/', '--ownership', 'recommended', str(pkg)], check=True)
        resources = work / 'resources'
        resources.mkdir()
        welcome = resources / 'Welcome.html'
        welcome.write_text('<html><meta charset="utf-8"><body><h1>Magic Bay LTE 1.4.2</h1>'
            '<p>Intel macOS 13+ · Lenovo Magic Bay LTE (17ef:7240)</p>'
            '<p>需要先安装 Apple 命令行工具（Python 3.9+）。安装会添加菜单栏应用和 root 后台助手。'
            '更新会短暂停止旧 LTE 服务，请先恢复其他网络并退出旧界面。</p>'
            '<p>全新安装默认关闭 LTE；安装后从“应用程序”打开 Magic Bay LTE 并主动启用。'
            '日常启停无需重复管理员密码。</p>'
            '<p>社区项目，未经过 Apple 公证，仅在 macOS 15.8.1 的一台 Intel 机器验证。'
            '完整对应源码随包提供。许可证：AGPL-3.0-only；第三方声明见 NOTICE。</p></body></html>')
        distribution = ET.Element('installer-gui-script', {'minSpecVersion': '2'})
        ET.SubElement(distribution, 'title').text = 'Magic Bay LTE'
        ET.SubElement(distribution, 'welcome', {'file': 'Welcome.html'})
        ET.SubElement(distribution, 'license', {'file': 'LICENSE'})
        ET.SubElement(distribution, 'options', {'customize': 'never', 'require-scripts': 'true', 'hostArchitectures': 'x86_64'})
        domains = ET.SubElement(distribution, 'domains', {'enable_localSystem': 'true', 'enable_currentUserHome': 'false', 'enable_anywhere': 'false'})
        volume = ET.SubElement(distribution, 'volume-check')
        ET.SubElement(volume, 'allowed-os-versions')
        ET.SubElement(volume.find('allowed-os-versions'), 'os-version', {'min': '13.0'})
        outline = ET.SubElement(distribution, 'choices-outline')
        ET.SubElement(outline, 'line', {'choice': 'default'})
        choice = ET.SubElement(distribution, 'choice', {'id': 'default', 'visible': 'false', 'title': 'Magic Bay LTE'})
        ET.SubElement(choice, 'pkg-ref', {'id': IDENTIFIER})
        ET.SubElement(distribution, 'pkg-ref', {'id': IDENTIFIER, 'version': VERSION}).text = 'component.pkg'
        xml = work / 'Distribution.xml'
        ET.ElementTree(distribution).write(xml, encoding='utf-8', xml_declaration=True)
        shutil.copyfile(BASE / 'LICENSE', resources / 'LICENSE')
        package = out / (prefix + '-macOS-Intel.pkg')
        subprocess.run(['/usr/bin/productbuild', '--distribution', str(xml), '--resources', str(resources),
            '--package-path', str(work), str(package)], check=True)
    (out / 'SHA256SUMS.txt').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in (package, source)))
    print('Packaged, NOT installed: ' + str(package))


if __name__ == '__main__':
    main()

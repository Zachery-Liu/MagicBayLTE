# SPDX-License-Identifier: AGPL-3.0-only
"""Build and test offline. Does not start LTE or modify host network settings."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
RUNTIME = BUILD / 'runtime'
TOOLS = BUILD / 'tools'
LIBUSB = BUILD / 'deps/libusb-1.0.29/libusb'
RUNTIME_SOURCES = ('lte_auto.py', 'failover_policy.py', 'lte_helper.py',
                   'lte_service.py', 'network_events.py')


def environment():
    return dict(os.environ,
        PYTHONPATH=os.pathsep.join(str(ROOT / name) for name in ('backend', 'tools')),
        PYTHONPYCACHEPREFIX=str(BUILD / 'cache/python'))


def run(args):
    result = subprocess.run(args, cwd=ROOT, env=environment(), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout)
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path in (RUNTIME, TOOLS, BUILD / 'validation', BUILD / 'cache/python'):
        path.mkdir(parents=True, exist_ok=True)
    transcript = run([sys.executable, 'scripts/build_libusb.py'])
    transcript += run([sys.executable, 'engine/adapt_engine.py'])
    transcript += run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                       '-p', 'test_*.py', '-v'])
    compiler = ['clang', '-target', 'x86_64-apple-macosx13.0']
    with tempfile.TemporaryDirectory(prefix='magicbay-build-') as directory:
        temporary = Path(directory)
        for name in ('transport', 'network', 'modem', 'session', 'idle'):
            program = temporary / ('test_' + name)
            args = compiler + ['-g', '-O1', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-I', str(LIBUSB)]
            if name in ('transport', 'idle'):
                args += ['-Wno-unused-function']
            args += ['tests/test_' + name + '.c']
            if name in ('network', 'modem', 'idle'):
                args += ['-framework', 'CoreFoundation']
            if name == 'network':
                args += ['-framework', 'SystemConfiguration']
            run(args + ['-o', str(program)])
            transcript += run([str(program)])
        watcher = temporary / 'magicbay_network_watch'
        run(compiler + ['-O2', '-Wall', '-Wextra', '-Werror', '-fblocks',
            'engine/network_watch.c', '-framework', 'CoreFoundation',
            '-framework', 'SystemConfiguration', '-framework', 'IOKit', '-o', str(watcher)])
        common = compiler + ['-O2', '-Wall', '-Wextra', '-Werror',
            '-I', str(LIBUSB), '-I', 'engine', 'build/engine/magicbay_lte.c',
            str(LIBUSB / '.libs/libusb-1.0.a'), '-lpthread', '-framework', 'IOKit',
            '-framework', 'CoreFoundation', '-framework', 'Security',
            '-framework', 'SystemConfiguration', '-lobjc']

        def compile_variant(mode):
            name = 'magicbay_lte' + ('_' + mode if mode else '')
            definitions = {'test': 'MAGICBAY_TEST', 'managed': 'MAGICBAY_MANAGED'}
            args = common + (['-D' + definitions[mode], '-Wno-unused-function'] if mode else [])
            run(args + ['-o', str(temporary / name)])
            return name

        with ThreadPoolExecutor(max_workers=2) as pool:
            names = list(pool.map(compile_variant, ('', 'test', 'managed')))
        # Stage the installed service layout only after every check succeeds.
        for name in names + ['magicbay_network_watch']:
            directory = RUNTIME if name in ('magicbay_lte_managed', 'magicbay_network_watch') else TOOLS
            pending = directory / (name + '.new')
            shutil.copyfile(temporary / name, pending)
            pending.chmod(0o755)
            pending.replace(directory / name)
    for name in RUNTIME_SOURCES:
        shutil.copyfile(ROOT / 'backend' / name, RUNTIME / name)
    runtime_names = RUNTIME_SOURCES + ('magicbay_lte_managed', 'magicbay_network_watch')
    runtime_manifest = {'offline_tests': 'passed',
        'sha256': {name: digest(RUNTIME / name) for name in runtime_names}}
    (RUNTIME / 'build-manifest.json').write_text(json.dumps(runtime_manifest, indent=2))
    source_files = []
    for pattern in ('backend/*.py', 'engine/*.py', 'engine/*.h', 'engine/*.c',
                    'tools/*.py', 'tests/*.py', 'tests/*.c', 'scripts/build*.py'):
        source_files.extend(ROOT.glob(pattern))
    artifacts = [RUNTIME / name for name in runtime_names]
    artifacts += [RUNTIME / 'build-manifest.json', TOOLS / 'magicbay_lte',
                  TOOLS / 'magicbay_lte_test', BUILD / 'engine/magicbay_lte.c']
    manifest = {'built_at_utc': datetime.now(timezone.utc).isoformat(),
                'hardware_tested': False, 'offline_tests': 'passed',
                'sha256': {str(path.relative_to(ROOT)): digest(path)
                           for path in sorted(set(source_files + artifacts))}}
    (BUILD / 'validation/backend.json').write_text(json.dumps(manifest, indent=2))
    (BUILD / 'validation/offline-tests.log').write_text(transcript)
    print('PASS: offline tests and native builds; runtime staged in build/runtime. Hardware NOT tested.')


if __name__ == '__main__':
    main()

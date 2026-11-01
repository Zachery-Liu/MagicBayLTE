# SPDX-License-Identifier: AGPL-3.0-only
"""Regenerate, run offline tests, build all variants. Never runs an LTE engine."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent


def run(args):
    result = subprocess.run(args, cwd=BASE, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout)
    return result.stdout


def main():
    transcript = run([sys.executable, 'scripts/build_libusb.py'])
    transcript += run([sys.executable, 'adapt_engine.py'])
    transcript += run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                       '-p', 'test_*.py', '-v'])
    with tempfile.TemporaryDirectory(prefix='magicbay-build-') as directory:
        temporary = Path(directory)
        transport = temporary / 'test_transport'
        run(['clang', '-target', 'x86_64-apple-macosx13.0', '-g', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
             '-fsanitize=address,undefined', '-I', 'libusb-1.0.29/libusb',
             'tests/test_transport.c', '-o', str(transport)])
        transcript += run([str(transport)])
        network = temporary / 'test_network'
        run(['clang', '-target', 'x86_64-apple-macosx13.0', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', 'tests/test_network.c', '-framework',
             'CoreFoundation', '-framework', 'SystemConfiguration', '-o', str(network)])
        transcript += run([str(network)])
        modem = temporary / 'test_modem'
        run(['clang', '-target', 'x86_64-apple-macosx13.0', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-I', 'libusb-1.0.29/libusb', 'tests/test_modem.c',
             '-framework', 'CoreFoundation', '-o', str(modem)])
        transcript += run([str(modem)])
        session = temporary / 'test_session'
        run(['clang', '-target', 'x86_64-apple-macosx13.0', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-I', 'libusb-1.0.29/libusb',
             'tests/test_session.c', '-o', str(session)])
        transcript += run([str(session)])
        idle=temporary/'test_idle'
        run(['clang', '-target', 'x86_64-apple-macosx13.0','-g','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function',
             '-fsanitize=address,undefined','-I','libusb-1.0.29/libusb','tests/test_idle.c',
             '-framework','CoreFoundation','-o',str(idle)])
        transcript+=run([str(idle)])
        watcher=temporary/'magicbay_network_watch'
        run(['clang', '-target', 'x86_64-apple-macosx13.0','-O2','-Wall','-Wextra','-Werror','-fblocks','network_watch.c',
             '-framework','CoreFoundation','-framework','SystemConfiguration','-framework','IOKit','-o',str(watcher)])
        common = ['clang', '-target', 'x86_64-apple-macosx13.0', '-O2', '-Wall', '-Wextra', '-Werror', '-I', 'libusb-1.0.29/libusb',
                  'magicbay_lte.c', 'libusb-1.0.29/libusb/.libs/libusb-1.0.a', '-lpthread',
                  '-framework', 'IOKit', '-framework', 'CoreFoundation', '-framework', 'Security',
                  '-framework', 'SystemConfiguration', '-lobjc']

        def compile_variant(mode):
            name = 'magicbay_lte' + ('_'+mode if mode else '')
            define = {'test':'MAGICBAY_TEST','managed':'MAGICBAY_MANAGED'}
            args = common + (['-D'+define[mode], '-Wno-unused-function'] if mode else [])
            run(args + ['-o', str(temporary / name)])
            return name

        with ThreadPoolExecutor(max_workers=2) as pool:
            names = list(pool.map(compile_variant, ['', 'test', 'managed']))
        # Publish only after both variants and all offline checks succeed.
        for name in names+['magicbay_network_watch']:
            target = BASE / (name + '.new')
            target.write_bytes((temporary / name).read_bytes())
            target.chmod(0o755)
            target.replace(BASE / name)
    files = ['magicbay_lte.c', 'magicbay_ntb.h', 'magicbay_bridge.h', 'adapt_engine.py',
             'lte_control.py', 'test_data.py', 'magicbay_lte', 'magicbay_lte_test', 'build_offline.py',
             'magicbay_network.h', 'magicbay_lte_managed', 'lte_auto.py', 'failover_policy.py', 'lte_service.py', 'lte_helper.py', 'tests/test_helper.py',
             'magicbay_modem_codec.h', 'magicbay_modem.h', 'tests/test_modem.c',
             'magicbay_session.h', 'tests/test_session.c', 'magicbay_idle.h', 'tests/test_idle.c',
             'network_watch.c','network_events.py','magicbay_network_watch','tests/test_network_events.py',
             'tests/test_transport.c', 'tests/test_network.c', 'tests/test_controller.py', 'tests/test_auto.py']
    manifest = {'built_at_utc': datetime.now(timezone.utc).isoformat(),
                'hardware_tested': False, 'offline_tests': 'passed',
                'sha256': {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest()
                           for name in files}}
    (BASE / 'build-manifest.json').write_text(json.dumps(manifest, indent=2))
    (BASE / 'offline-validation.log').write_text(transcript)
    print('PASS: offline tests; global/test/managed LTE binaries built. Hardware NOT tested.')


if __name__ == '__main__':
    main()

# SPDX-License-Identifier: AGPL-3.0-only
"""Explicitly authorized single-target LTE test. Never disables Wi-Fi or changes default routes.

Requires a separately agreed test window AND --allow-lte-test. The flag is not approval.
Claims the module, starts a bearer, configures utun, adds only 223.5.5.5's host route.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import time
import lte_control as control

BASE = Path(__file__).resolve().parent


def run(args, timeout=15):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return {'exit': p.returncode, 'output': p.stdout + p.stderr}


def route_identity(result):
    return {key: match.group(1) if (match := re.search(r'^\s*' + key + r':\s*(\S+)',
            result['output'], re.M)) else None for key in ('gateway', 'interface')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-lte-test', action='store_true', help='Only use after an explicitly agreed test window')
    parser.add_argument('--duration', type=int, default=45, choices=range(15, 181), metavar='15..180')
    args = parser.parse_args(argv)
    if not args.allow_lte_test:
        parser.error('未授权的测试不会运行：先约定测试窗口，再传入 --allow-lte-test。')
    if os.geteuid() != 0:
        parser.error('临时 LTE 接口需要管理员权限。')
    with control.LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if control.running():
            raise RuntimeError('已有 LTE 进程，不运行测试以免干扰现有会话。')
        # Refuse a stale diagnostic binary whose source differs from this build.
        import hashlib
        manifest = json.loads((BASE / 'build-manifest.json').read_text())
        for name in ('magicbay_lte.c', 'magicbay_ntb.h', 'magicbay_bridge.h', 'magicbay_lte_test'):
            if hashlib.sha256((BASE/name).read_bytes()).hexdigest() != manifest['sha256'][name]:
                raise RuntimeError('源码/测试二进制不同步，请先离线构建。')
        return test(args.duration)


def test(duration):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory = BASE/'logs'
    directory.mkdir(exist_ok=True)
    log = directory/('data-' + stamp + '.log')
    report_path = directory/('data-' + stamp + '.json')
    report = {'started_utc': stamp, 'duration': duration, 'log': str(log), 'samples': []}
    process = None
    try:
        report['default_before'] = run(['/sbin/route', '-n', 'get', 'default'])
        report['route_before'] = run(['/sbin/route', '-n', 'get', '223.5.5.5'])
        report['wifi_before'] = run(['/usr/sbin/networksetup', '-getairportpower', 'en2'])
        if (report['default_before']['exit'] or report['wifi_before']['exit'] or
                not report['wifi_before']['output'].strip().endswith(': On')):
            raise RuntimeError('当前 Wi-Fi/默认路由不符合保留现有网络的测试前提。')
        with log.open('w') as output:
            process = subprocess.Popen([str(BASE/'magicbay_lte_test')], stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       env=dict(os.environ, MAGICBAY_DURATION=str(duration+60)))
        deadline = time.monotonic()+45
        while process.poll() is None and time.monotonic()<deadline:
            text = log.read_text(errors='replace')
            if 'utun + routes ready' in text:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('LTE 测试接口未就绪。')
        match = re.search(r'UTUN\s*:\s*(utun\d+)', text)
        if not match:
            raise RuntimeError('没有找到测试接口。')
        interface = report['interface'] = match.group(1)
        started = time.monotonic()
        while time.monotonic()-started < duration:
            if process.poll() is not None:
                raise RuntimeError('LTE 通信程序提前退出。')
            if route_identity(run(['/sbin/route', '-n', 'get', 'default'])) != route_identity(report['default_before']):
                raise RuntimeError('默认路由发生变化，停止测试；不自动调整网络。')
            route = run(['/sbin/route', '-n', 'get', '223.5.5.5'])
            if not re.search(r'interface:\s*'+re.escape(interface)+r'\b', route['output']):
                raise RuntimeError('测试目标未路由到 LTE。')
            sample = {'utc': datetime.now(timezone.utc).isoformat(), 'elapsed': time.monotonic()-started}
            sample['https'] = run(['/usr/bin/curl', '--noproxy', '*', '--interface', interface,
                                   '--ipv4', '--silent', '--show-error', '--fail', '--max-time', '8',
                                   '--resolve', 'dns.alidns.com:443:223.5.5.5',
                                   'https://dns.alidns.com/resolve?name=example.com&type=A'])
            report['samples'].append(sample)
            result = json.loads(sample['https']['output']) if sample['https']['exit']==0 else {}
            if result.get('Status')!=0 or not result.get('Answer'):
                raise RuntimeError('LTE HTTPS 检查未通过。')
            if len(report['samples'])==1:
                report['ping'] = run(['/sbin/ping', '-n', '-c', '3', '-W', '1500', '223.5.5.5'])
                report['dns'] = run(['/usr/bin/dig', '@223.5.5.5', 'example.com', 'A', '+tries=1', '+time=3'])
            time.sleep(min(5, max(0, duration-(time.monotonic()-started))))
        report['passed'] = (process.poll() is None and report['ping']['exit']==0 and
                            report['dns']['exit']==0)
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = str(error) or type(error).__name__
        report['passed'] = False
    finally:
        if process is not None:
            report['stopped'] = control.shutdown(process)
            report['engine_exit'] = process.poll()
            if not report['stopped']:
                token = control.identity(process.pid, diagnostic=True)
                control.save_state({'pid': process.pid, 'process_started': token,
                                    'phase': 'stopping', 'interface': report.get('interface', ''),
                                    'diagnostic': True, 'log': str(log)})
                report['passed'] = False
        try:
            report['default_after'] = run(['/sbin/route', '-n', 'get', 'default'])
            report['route_after'] = run(['/sbin/route', '-n', 'get', '223.5.5.5'])
            report['wifi_after'] = run(['/usr/sbin/networksetup', '-getairportpower', 'en2'])
            report['default_preserved'] = route_identity(report['default_before']) == route_identity(report['default_after'])
            if not report['default_preserved']:
                report['passed'] = False
        except Exception as error:
            report['snapshot_error'] = str(error)
            report['passed'] = False
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('保存至：'+str(report_path))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())

# SPDX-License-Identifier: AGPL-3.0-only
"""Manual LTE lifecycle. Importing this module never starts USB/network work."""
from pathlib import Path
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1] / 'build/tools'
ENGINE = BASE / 'magicbay_lte'
STATE = BASE / 'connection-state.json'
LOG = BASE / 'connection.log'
LOCK = Path('/var/run/magicbay-lte.lock')


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


def identity(pid, diagnostic=False):
    """A start-time token prevents stale PID files from identifying another process."""
    if pid <= 1:
        return None
    comm = command(['/bin/ps', '-p', str(pid), '-o', 'comm='])
    born = command(['/bin/ps', '-p', str(pid), '-o', 'lstart='])
    expected = ENGINE.with_name('magicbay_lte_test') if diagnostic else ENGINE
    if comm.returncode == 0 and born.returncode == 0 and comm.stdout.strip() == str(expected):
        return born.stdout.strip() or None
    return None


def running():
    try:
        state = json.loads(STATE.read_text())
        token = identity(int(state['pid']), diagnostic=bool(state.get('diagnostic')))
        if token and (not state.get('process_started') or state['process_started'] == token):
            return state
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    return None


def save_state(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temporary.replace(STATE)


def conflict():
    result = command(['/usr/sbin/netstat', '-rn', '-f', 'inet'])
    if result.returncode:
        raise RuntimeError('无法读取路由表，停止连接。')
    return any(re.search(r'\butun\d+\b', line) for line in result.stdout.splitlines())


def route_matches(interface):
    if not re.fullmatch(r'utun\d+', interface):
        return False
    route = command(['/sbin/route', '-n', 'get', '223.5.5.5'])
    return route.returncode == 0 and bool(re.search(
        r'interface:\s*' + re.escape(interface) + r'\b', route.stdout))


def archive_log():
    if LOG.exists():
        directory = BASE / 'logs'
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        LOG.rename(directory / ('connection-' + stamp + '.log'))


def shutdown(process):
    if process.poll() is None:
        try:
            process.send_signal(signal.SIGUSR1)
        except ProcessLookupError:
            process.wait(timeout=1)
            return True
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            return False
    return True


def start():
    state = running()
    if state:
        print('LTE 通信程序已运行，状态：' + state.get('phase', 'unknown'))
        return 0
    if conflict():
        print('检测到代理/VPN 的 TUN 路由，暂不接管网络。请保留当前连接并先约定测试窗口。')
        return 2
    if not ENGINE.is_file():
        raise RuntimeError('找不到 LTE 通信程序。')
    archive_log()
    process = None
    connected = False
    failure = '等待接口就绪超时'
    try:
        with LOG.open('w') as output:
            process = subprocess.Popen([str(ENGINE)], stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True,
                                       env=dict(os.environ, MAGICBAY_DURATION='0'))
        state = {'pid': process.pid, 'interface': '', 'started': time.time(),
                 'phase': 'starting', 'process_started': identity(process.pid)}
        if not state['process_started']:
            raise RuntimeError('通信程序已退出或无法核实进程身份。')
        save_state(state)
        deadline = time.monotonic() + 45
        while process.poll() is None and time.monotonic() < deadline:
            text = LOG.read_text(errors='replace')
            if 'utun + routes ready' not in text:
                time.sleep(0.25)
                continue
            match = re.search(r'UTUN\s*:\s*(utun\d+)', text)
            if not match:
                raise RuntimeError('未找到生成的 LTE 接口。')
            interface = match.group(1)
            state['interface'] = interface
            save_state(state)
            if not route_matches(interface):
                raise RuntimeError('指定测试目标未路由到 LTE 接口。')
            time.sleep(2)
            if process.poll() is not None:
                raise RuntimeError('通信程序在健康检查前退出。')
            health = subprocess.run([
                '/usr/bin/curl', '--noproxy', '*', '--interface', interface, '-4',
                '-sS', '--fail', '--max-time', '8', '--resolve',
                'dns.alidns.com:443:223.5.5.5',
                'https://dns.alidns.com/resolve?name=example.com&type=A'],
                capture_output=True, text=True, timeout=10)
            result = json.loads(health.stdout) if health.returncode == 0 else {}
            if (result.get('Status') != 0 or not result.get('Answer') or
                    process.poll() is not None or not route_matches(interface)):
                raise RuntimeError('LTE HTTPS 健康检查失败或通信程序已退出。')
            state['phase'] = 'connected'
            state['health_checked'] = time.time()
            save_state(state)
            connected = True
            print('Magic Bay LTE 已连接，指定目标 HTTPS 检查通过。\n'
                  '当前支持 IPv4；这不代表已验证长时间稳定性。\n'
                  '双击“断开LTE.command”可结束连接。')
            return 0
        if process.poll() is not None:
            failure = '通信程序提前退出，exit=' + str(process.returncode)
    except (Exception, KeyboardInterrupt) as error:
        failure = str(error) or type(error).__name__
    finally:
        if not connected and process is not None:
            if shutdown(process):
                STATE.unlink(missing_ok=True)
            else:
                save_state({'pid': process.pid, 'interface': '', 'phase': 'stopping',
                            'process_started': identity(process.pid), 'failure': failure})
                failure += '；程序仍在退出，请稍后运行断开工具'
    print('LTE 连接未完成：' + failure + '。详细记录见 connection.log。')
    return 1


def stop():
    state = running()
    if not state:
        print('LTE 当前未运行。')
        return 0
    os.kill(int(state['pid']), signal.SIGUSR1)
    deadline = time.monotonic() + 25
    while running() and time.monotonic() < deadline:
        time.sleep(0.25)
    if running():
        print('LTE 正在退出，请稍后再检查连接状态。')
        return 1
    STATE.unlink(missing_ok=True)
    print('LTE 通信程序已退出。')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    action = argv[0] if argv else 'status'
    if action not in ('start', 'stop', 'status', 'check'):
        print('用法：lte_control.py start|stop|status|check')
        return 2
    if action in ('status', 'check'):
        state = running()
        if state:
            phase = state.get('phase', 'unknown')
            if phase == 'connected' and route_matches(state.get('interface', '')):
                print('LTE 已连接：' + state['interface'] + '（未重新发送健康检查流量）')
            else:
                print('LTE 进程仍在运行，状态：' + phase + '；当前不能确认联网。')
            return 10 if action == 'check' else 0
        print('LTE 当前未连接。')
        if STATE.exists() and LOG.exists():
            errors = [line for line in LOG.read_text(errors='replace').splitlines()
                      if 'USB RX' in line or 'USB TX' in line or 'libusb native:' in line]
            if errors:
                print('上次 USB 通信记录：' + errors[-1])
        if action == 'check':
            if conflict():
                print('检测到 TUN 路由，暂不接管网络。')
                return 2
            print('未检测到 TUN 路由；尚未测试 LTE。')
        return 0
    if os.geteuid() != 0:
        print('需要系统管理员授权。')
        return 1
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('另一项 LTE 连接/断开操作正在进行。')
            return 1
        return start() if action == 'start' else stop()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('LTE 操作失败：' + str(error))
        sys.exit(1)

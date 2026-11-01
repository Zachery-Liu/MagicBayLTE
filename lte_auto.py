# SPDX-License-Identifier: AGPL-3.0-only
"""Wi-Fi/Ethernet preferred, supervised LTE fallback. No Wi-Fi/proxy toggles.

Normal run is enabled explicitly by start. self-test changes the preferred route
while keeping Wi-Fi enabled and requires a separately agreed test window.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import stat
import threading
from failover_policy import Policy
from network_events import NetworkEvents

BASE = Path(__file__).resolve().parent
ENGINE = BASE/'magicbay_lte_managed'
STATE = BASE/'auto-state.json'
# Shared by the installed service, workspace controller and diagnostic runner.
LOCK = Path('/var/run/magicbay-lte.lock')
STOP = False
RECONNECT = False
ENDPOINTS = [('dns.alidns.com', '223.5.5.5', '/resolve?name=example.com&type=A'),
             ('cloudflare-dns.com', '1.1.1.1', '/dns-query?name=example.com&type=A')]


def command(args, timeout=10):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def log(message):
    print(datetime.now(timezone.utc).isoformat(), message, flush=True)


def write_state(state):
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    pending = STATE.with_suffix('.new')
    pending.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    pending.chmod(0o644)
    pending.replace(STATE)


def birth(pid):
    if pid <= 1:
        return None
    result = command(['/bin/ps', '-p', str(pid), '-o', 'lstart='])
    return result.stdout.strip() if result.returncode == 0 else None


def alive():
    try:
        state = json.loads(STATE.read_text())
        if state.get('birth') and birth(int(state['pid'])) == state['birth']:
            args = command(['/bin/ps', '-p', str(state['pid']), '-o', 'args=']).stdout
            if str(BASE/'lte_auto.py') in args and re.search(r'\brun\b', args):
                return state
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        pass
    return None


def orphan_engine():
    """Do not claim USB while a previous supervisor's engine is still cleaning up."""
    try:
        state=json.loads(STATE.read_text())
        pid=int(state.get('engine_pid',0))
        if state.get('engine_birth') and birth(pid)==state['engine_birth']:
            comm=command(['/bin/ps','-p',str(pid),'-o','comm='])
            if comm.returncode==0 and comm.stdout.strip()==str(ENGINE):
                return pid
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):
        pass
    return None


def physical_interfaces():
    result = command(['/usr/sbin/networksetup', '-listnetworkserviceorder'])
    if result.returncode:
        raise RuntimeError('Cannot read network service order')
    names = list(dict.fromkeys(re.findall(r'Device:\s*(en\d+)\)', result.stdout)))
    usable = []
    for name in names:
        data = command(['/sbin/ifconfig', name])
        if data.returncode:
            continue
        addresses = re.findall(r'^\s*inet\s+(\S+)', data.stdout, re.M)
        if any(not (ipaddress.ip_address(x).is_link_local or ipaddress.ip_address(x).is_loopback)
               for x in addresses):
            usable.append(name)
    return usable


def default_route():
    result = command(['/sbin/route', '-n', 'get', 'default'])
    return {key: match.group(1) if (match := re.search(r'^\s*'+key+r':\s*(\S+)', result.stdout, re.M))
            else None for key in ('gateway', 'interface')}


def interface_expensive(interface):
    if re.fullmatch(r'utun\d+',interface) is None:
        return None
    result=command(['/sbin/ifconfig','-v',interface])
    if result.returncode: return None
    return re.search(r'\bEXPENSIVE\b',result.stdout) is not None


def system_proxy():
    data = command(['/usr/sbin/scutil', '--proxy']).stdout
    keys = ('HTTPEnable', 'HTTPProxy', 'HTTPPort', 'HTTPSEnable', 'HTTPSProxy', 'HTTPSPort',
            'SOCKSEnable', 'SOCKSProxy', 'SOCKSPort', 'ProxyAutoConfigEnable', 'ProxyAutoConfigURLString')
    return {key: match.group(1).strip() if (match := re.search(r'^\s*'+key+r'\s*:\s*(.+)$', data, re.M))
            else None for key in keys}


def app_health():
    """A new application request using current system HTTP proxy, if configured."""
    proxy = system_proxy()
    args = ['/usr/bin/curl', '-4', '-fsS', '--connect-timeout', '3', '--max-time', '6',
            '--max-filesize', '16384', '--resolve', 'dns.alidns.com:443:223.5.5.5',
            'https://dns.alidns.com/resolve?name=example.com&type=A']
    if proxy.get('HTTPSEnable')=='1' and proxy.get('HTTPSProxy') and proxy.get('HTTPSPort'):
        args[1:1] = ['--proxy', 'http://'+proxy['HTTPSProxy']+':'+proxy['HTTPSPort'], '--noproxy', '']
    else:
        args[1:1] = ['--noproxy', '*']
    try:
        result = command(args, timeout=8)
        value = json.loads(result.stdout) if result.returncode==0 else {}
        return value.get('Status')==0 and bool(value.get('Answer'))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def health_request(interface, endpoint, cancelled):
    host, address, path = endpoint
    if cancelled.is_set():
        return False
    process=None
    try:
        process=subprocess.Popen(['/usr/bin/curl', '--noproxy', '*', '--interface', interface,
            '-4', '-fsS', '--connect-timeout', '2', '--max-time', '4',
            '--max-filesize', '16384', '-H', 'Accept: application/dns-json',
            '--resolve', f'{host}:443:{address}', 'https://'+host+path],
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,close_fds=True)
        deadline=time.monotonic()+5
        while not cancelled.is_set() and not STOP and time.monotonic()<deadline:
            try:
                output,_=process.communicate(timeout=0.1)
                value=json.loads(output) if process.returncode==0 else {}
                valid=(isinstance(value,dict) and value.get('Status')==0 and
                       isinstance(value.get('Answer'),list) and bool(value['Answer']))
                if valid: cancelled.set()
                return valid
            except subprocess.TimeoutExpired:
                pass
        return False
    except (ValueError,OSError,subprocess.SubprocessError):
        return False
    finally:
        if process is not None:
            if process.poll() is None:
                # Cancel only our own read-only curl process, never an app/network service.
                try: process.terminate()
                except ProcessLookupError: pass
                try: process.communicate(timeout=0.5)
                except subprocess.TimeoutExpired:
                    try: process.kill()
                    except ProcessLookupError: pass
                    process.communicate(timeout=0.5)
            if process.stdout: process.stdout.close()


def health(interface):
    if re.fullmatch(r'(?:en|utun)\d+',interface) is None:
        return False
    cancelled=threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(health_request,interface,endpoint,cancelled) for endpoint in ENDPOINTS]
        for future in as_completed(futures):
            if future.result():
                cancelled.set()
                return True
    return False


def wait_for_observation(events, interval):
    deadline=time.monotonic()+interval
    while not STOP and not RECONNECT:
        remaining=deadline-time.monotonic()
        if remaining<=0 or events.wait(min(0.5,remaining)):
            return


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def proxy_compatibility(own_interface=None):
    """Only reads runtime config; never PATCHes/restarts a proxy or VPN."""
    table = command(['/usr/sbin/netstat', '-rn', '-f', 'inet'])
    if table.returncode:
        raise RuntimeError('Cannot read route table')
    tunnels = set(re.findall(r'\butun\d+\b', table.stdout)) - {own_interface}
    if not tunnels:
        return {'compatible': True, 'tun': None}
    uid = Path('/dev/console').stat().st_uid
    path = f'/var/run/clash-verge-service/users/{uid}/verge-mihomo.sock'
    connection = UnixHTTP(path)
    try:
        connection.request('GET', '/configs')
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('Cannot read Clash runtime configuration')
        config = json.loads(response.read(65537))
        tun = config.get('tun', {})
        device = tun.get('device')
        compatible = (tun.get('enable') is True and tun.get('auto-detect-interface') is True
                      and not config.get('interface-name') and tunnels <= {device})
        return {'compatible': compatible, 'tun': device,
                'reason': None if compatible else 'VPN or pinned/unknown proxy interface requires review'}
    except (OSError, ValueError, http.client.HTTPException) as error:
        return {'compatible': False, 'reason': 'Cannot verify running proxy: '+str(error)}
    finally:
        connection.close()


class Engine:
    def __init__(self):
        self.process = None
        self.writer = None
        self.info = None
        self.log_path = None
        self.active = False

    @property
    def data_ready(self):
        return bool(self.info and self.info.get('interface'))

    @property
    def monitoring(self):
        return bool(self.info and self.info.get('mode')=='monitor')

    def start(self, monitor=False):
        reader, self.writer = os.pipe()
        directory = BASE/'logs'
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        self.log_path = directory/('managed-'+stamp+'.log')
        environment=dict(os.environ)
        environment.pop('MAGICBAY_MONITOR_ONLY',None)
        if monitor: environment['MAGICBAY_MONITOR_ONLY']='1'
        try:
            with self.log_path.open('w') as output:
                self.process = subprocess.Popen([str(ENGINE)], stdout=output, stderr=subprocess.STDOUT,
                    pass_fds=(reader,), start_new_session=True,
                    env=dict(environment, MAGICBAY_CONTROL_FD=str(reader), MAGICBAY_DURATION='0',
                                      MAGICBAY_TELEMETRY_PATH=str(BASE/'modem-state.json'),
                                      MAGICBAY_SIGNAL_REQUEST_PATH=str(BASE/'signal-request')))
        finally:
            os.close(reader)
        deadline = time.monotonic()+45
        while not STOP and self.process.poll() is None and time.monotonic()<deadline:
            text = self.log_path.read_text(errors='replace')
            marker='MB_AUTO_MONITOR_READY' if monitor else 'MB_AUTO_READY'
            match = re.search(r'^'+marker+r' (\{.+\})$', text, re.M)
            if match:
                self.info = json.loads(match.group(1))
                if monitor and self.info.get('activation_state')!=3:
                    raise RuntimeError('LTE data session is not confirmed inactive')
                return
            time.sleep(0.25)
        raise RuntimeError('LTE standby interface failed to start; see '+str(self.log_path))

    def switch(self, active):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError('LTE process has exited')
        os.write(self.writer, b'A' if active else b'S')
        marker = 'MB_AUTO_STATE '+('active' if active else 'standby')
        # Count a new acknowledgement; do not accept an old log line.
        deadline = time.monotonic()+6
        previous = getattr(self, '_acks', {}).get(marker, 0)
        while self.process.poll() is None and time.monotonic()<deadline:
            count = self.log_path.read_text(errors='replace').count(marker)
            if count>previous:
                if not hasattr(self, '_acks'):
                    self._acks = {}
                self._acks[marker] = count
                self.active = active
                return
            time.sleep(0.1)
        raise RuntimeError('LTE network state update not acknowledged')

    def close(self):
        if self.writer is not None:
            os.close(self.writer)  # EOF also cleans up after a supervisor crash.
            self.writer = None
        if self.process and self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGUSR1)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                return False
        self.info = None
        self.active = False
        return True


class TrafficTotals:
    """Actual IP bridge bytes, accumulated across data/monitor engine restarts."""
    def __init__(self):
        self.received=self.sent=0
        self.seen={}

    def sample(self,engine):
        if not engine.process or not engine.log_path: return
        try:
            data=json.loads((BASE/'modem-state.json').read_text())
            if data.get('engine_pid')!=engine.process.pid: return
            rx,tx=data['transfer_received'],data['transfer_sent']
            if type(rx) is not int or type(tx) is not int or not 0<=rx<2**64 or not 0<=tx<2**64: return
            key=str(engine.log_path)
            old_rx,old_tx=self.seen.get(key,(0,0))
            self.received+=max(0,rx-old_rx);self.sent+=max(0,tx-old_tx)
            self.seen[key]=(max(old_rx,rx),max(old_tx,tx))
        except (OSError,ValueError,KeyError,TypeError): pass

    def publish(self,state):
        state.update(transfer_received_total=self.received,transfer_sent_total=self.sent)


def record_engine(state,engine):
    state.update(engine_pid=engine.process.pid,engine_birth=birth(engine.process.pid),
                 engine_log=str(engine.log_path),engine_mode='monitor' if engine.monitoring else 'data')
    if engine.data_ready: state['interface']=engine.info['interface']
    else: state.pop('interface',None)


def release_data_session(engine,state,traffic):
    """Do not equate a rank change with ending LTE traffic. Close the actual bearer."""
    state.update(phase='returning',return_verified=False)
    write_state(state)
    traffic.sample(engine)
    if engine.active: engine.switch(False)
    if not engine.close():
        raise RuntimeError('LTE data engine still releasing; no completed-return claim')
    traffic.sample(engine)  # Engine flushes final IP byte counters before exiting.
    traffic.publish(state)
    state.update(active=False,data_session_closed_utc=datetime.now(timezone.utc).isoformat())
    state.pop('interface',None)
    write_state(state)


def verify_preferred_return(engine,results):
    return bool(engine.monitoring and results.get(default_route().get('interface')) is True and app_health())


def signal_stop(signum, frame):
    global STOP
    STOP = True


def signal_reconnect(signum,frame):
    global RECONNECT
    RECONNECT=True


class SignalRequest:
    """User may touch one protected inode to request a read-only RSSI query.

    The root-owned parent prevents replacement in production. No file content is
    interpreted, no shell command/arguments are accepted, and the engine rate-limits it.
    """
    def __init__(self):
        self.fd=os.open(BASE/'signal-request',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        info=os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            os.close(self.fd)
            raise RuntimeError('Unsafe signal request file')
        self.refresh_owner()

    def refresh_owner(self):
        uid=Path('/dev/console').stat().st_uid
        if os.fstat(self.fd).st_uid!=uid:
            os.fchown(self.fd,uid,-1)
        os.fchmod(self.fd,0o600)

    def close(self):
        os.close(self.fd)


def run(observe=False, duration=0, exercise=False):
    global STOP,RECONNECT
    STOP = RECONNECT = False
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
        signal.signal(sig, signal_stop)
    signal.signal(signal.SIGUSR2,signal_reconnect)
    if orphan_engine():
        raise RuntimeError('Previous LTE engine is still releasing its session; no new USB claim')
    state = {'pid': os.getpid(), 'birth': birth(os.getpid()), 'phase': 'starting',
             'active': False, 'observe_only': observe, 'exercise': exercise,
             'connection_started_utc': datetime.now(timezone.utc).isoformat(), 'retry_count': 0,
             'reconnect_count':0}
    policy = Policy()
    engine = Engine()
    traffic = TrafficTotals()
    return_pending=False
    started = time.monotonic()
    retry_at = 0
    failures = 0
    module_sequence=0
    lte_good, last_lte_probe = False, -1e9
    original_route, original_proxy = default_route(), system_proxy()
    initial_physical = physical_interfaces()
    exercise_phases = set()
    exercise_samples = []
    request=SignalRequest()
    events=NetworkEvents(BASE/'magicbay_network_watch')
    write_state(state)
    try:
        while not STOP and (not duration or time.monotonic()-started<duration):
            request.refresh_owner()
            now = time.monotonic()
            if RECONNECT:
                RECONNECT=False
                state.update(phase='reconnecting',active=engine.active)
                write_state(state)
                traffic.sample(engine)
                if not engine.close():
                    raise RuntimeError('LTE session still closing; reconnect deferred to prevent overlap')
                traffic.sample(engine)
                engine=Engine();policy=Policy();lte_good=None;return_pending=False
                failures=0;retry_at=now
                for key in ('interface','engine_pid','engine_birth','engine_log','engine_mode','connection_error'):
                    state.pop(key,None)
                state.update(active=False,reconnect_count=state['reconnect_count']+1,
                    connection_started_utc=datetime.now(timezone.utc).isoformat())
                log('Manual reconnect: LTE session closed; initialize a fresh control session')
            hardware=events.snapshot()
            sequence=hardware.get('module_sequence',0)
            present=hardware.get('module_present')
            if type(sequence) is int and sequence!=module_sequence:
                module_sequence=sequence
                traffic.sample(engine)
                if not engine.close():
                    raise RuntimeError('Previous USB handle still closing; refusing overlapping sessions')
                traffic.sample(engine)
                engine=Engine();policy.active=False;lte_good=None
                for key in ('interface','engine_pid','engine_birth','engine_log','engine_mode','connection_error'):
                    state.pop(key,None)
                failures=0
                retry_at=now+(1 if present is True else 0)
                state['connection_started_utc']=datetime.now(timezone.utc).isoformat()
                log('USB module '+('attached; immediate fresh initialization' if present else 'removed; await attachment'))
            if engine.process and engine.process.poll() is not None:
                log('LTE engine exited; network state released')
                traffic.sample(engine)
                engine.close()
                engine = Engine()
                policy.active = False
                lte_good = False
                failures += 1
                state['connection_started_utc'] = datetime.now(timezone.utc).isoformat()
                retry_at = now+min(30, 2**min(failures, 5))
            if engine.process is None and present is not False and now>=retry_at:
                try:
                    state.update(phase='starting', retry_count=failures)
                    write_state(state)
                    engine.start(monitor=not exercise)
                    failures = 0
                    last_lte_probe = -1e9
                    record_engine(state,engine)
                    state.pop('connection_error',None)
                    log('LTE '+('control-only standby; data session inactive' if engine.monitoring else 'data interface ready'))
                except Exception as error:
                    log(str(error))
                    state['connection_error'] = str(error)
                    if not engine.close():
                        raise RuntimeError('Previous LTE process has not stopped; refusing another USB session')
                    engine = Engine()
                    failures += 1
                    retry_at = time.monotonic()+min(30,2**min(failures,5))
            try:
                interfaces = physical_interfaces()
                with ThreadPoolExecutor(max_workers=max(1,len(interfaces))) as pool:
                    results = dict(zip(interfaces, pool.map(health, interfaces)))
                physical = any(results.values())
                best = next((x for x in interfaces if results[x]), None)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                physical, best, results = None, None, {}
                state['observation_error'] = str(error)
            if engine.monitoring and physical is False and not observe and not STOP:
                state.update(phase='starting',connection_started_utc=datetime.now(timezone.utc).isoformat())
                write_state(state)
                if not engine.close(): raise RuntimeError('Monitor did not release USB; no second session')
                engine=Engine();engine.start(monitor=False);record_engine(state,engine)
                last_lte_probe=-1e9
            if engine.data_ready and (physical is False or now-last_lte_probe>=(15 if policy.active else 120) or exercise):
                lte_good = health(engine.info['interface'])
                last_lte_probe = time.monotonic()
            elif engine.monitoring:
                lte_good=None
            compatibility = proxy_compatibility(engine.info['interface'] if engine.data_ready else None)
            if engine.data_ready and not engine.active and physical is True:
                os.write(engine.writer,b'P')
            target, reason = policy.step(time.monotonic(), physical, lte_good)
            if observe or not compatibility['compatible']:
                target = False
                policy.active = False
            if exercise:
                elapsed = time.monotonic()-started
                if elapsed<40 and (not engine.data_ready or not lte_good):
                    raise RuntimeError('Self-test LTE health failed; no activation')
                target = 15 <= elapsed < 40
                if not compatibility['compatible']:
                    raise RuntimeError('Self-test proxy compatibility check failed')
            # A recovered preferred network must have NO LTE data bearer behind a standby label.
            if engine.data_ready and not target and (engine.active or (physical is True and not exercise) or (exercise and time.monotonic()-started>=40)):
                release_data_session(engine,state,traffic)
                policy.active=False;return_pending=True;lte_good=None
                engine=Engine();engine.start(monitor=True);record_engine(state,engine)
                state['last_switch_utc']=datetime.now(timezone.utc).isoformat()
                state['last_switch_reason']='preferred network recovered; LTE data session ended'
                log('LTE data session closed; control-only standby')
            elif engine.data_ready and target != engine.active:
                engine.switch(target)
                state['last_switch_utc'] = datetime.now(timezone.utc).isoformat()
                state['last_switch_reason'] = reason if not exercise else 'authorized self-test'
                log('LTE active: '+state['last_switch_reason'])
                time.sleep(2)
            if return_pending and physical is True:
                # With no LTE IP interface, this application request cannot silently use LTE.
                verified=verify_preferred_return(engine,results)
                state['return_verified']=bool(verified)
                if verified: return_pending=False
            actual_route = default_route()
            if engine.data_ready and engine.active and actual_route['interface'] != engine.info['interface']:
                engine.switch(False)
                policy.active = False
                raise RuntimeError('LTE was not selected as system primary; released LTE rank')
            if exercise and engine.info:
                phase = 'active' if engine.active else ('returned' if engine.monitoring and not return_pending else 'standby')
                if not engine.active and actual_route != original_route:
                    raise RuntimeError('Self-test changed preferred route while in standby')
                if system_proxy() != original_proxy:
                    raise RuntimeError('Self-test app proxy settings changed')
                application_ok = app_health()
                exercise_samples.append({'utc':datetime.now(timezone.utc).isoformat(),
                    'phase':phase,'route':actual_route,'lte_health':lte_good,'application_health':application_ok})
                if not application_ok:
                    raise RuntimeError('Self-test application request through current proxy failed')
                exercise_phases.add(phase)
            state.update(retry_count=failures, phase=('waiting_module' if present is False else 'LTE' if engine.active else 'return_check' if return_pending else 'ready' if engine.monitoring else 'standby' if engine.data_ready else 'retrying'),
                         active=engine.active, physical_interface=best, physical_health=results,
                         lte_health=lte_good, proxy=compatibility, route=actual_route,
                         failed_observations=policy.failed, recovered_observations=policy.recovered,
                         exercise_phases=sorted(exercise_phases),exercise_samples=exercise_samples,
                         network_events=events.snapshot(), recovery_confirmation_seconds=8, recovery_minimum_samples=3)
            state['lte_expensive']=interface_expensive(engine.info['interface']) if engine.data_ready else None
            traffic.sample(engine);traffic.publish(state)
            write_state(state)
            # Recovery is sampled faster; physical interface events interrupt either wait.
            delay=2 if policy.active else 5
            if engine.process is None and present is not False:
                delay=min(delay,max(0.1,retry_at-time.monotonic()))
            wait_for_observation(events,delay)
        if exercise and exercise_phases != {'standby','active','returned'}:
            raise RuntimeError('Self-test did not complete all three phases')
        state['completed'] = True
    except BaseException as error:
        state['error'] = str(error)
        log('automatic LTE stopped: '+str(error))
    finally:
        events.close()
        request.close()
        cleaned = engine.close()
        traffic.sample(engine);traffic.publish(state)
        state.update(phase='stopped' if cleaned else 'cleanup_pending', active=False,
                     cleaned_up=cleaned, route_after=default_route(),
                     proxy_preserved=system_proxy()==original_proxy)
        if exercise:
            state['route_restored'] = state['route_after']==original_route
            state['physical_interfaces_before'] = initial_physical
            state['physical_interfaces_after'] = physical_interfaces()
            directory = BASE/'logs'
            directory.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            (directory/('auto-test-'+stamp+'.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2))
        write_state(state)
    return 0 if state.get('completed') and cleaned else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start','stop','status','run','self-test'])
    parser.add_argument('--observe', action='store_true')
    parser.add_argument('--duration', type=int, default=0)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.action=='status':
        state = alive()
        if args.json:
            print(json.dumps(state or {'phase':'not_running'},ensure_ascii=False,indent=2))
        elif not state:
            print('自动备用 LTE 当前未运行。')
        else:
            descriptions={'starting':'正在准备 LTE','standby':'Wi-Fi/有线优先，LTE 待命',
                          'LTE':'当前由 LTE 提供联网','ready':'LTE 已就绪，数据会话未建立','waiting_module':'等待模块接入，将自动初始化','return_check':'LTE 数据已关闭，正在核对原网络','retrying':'LTE 暂未就绪，等待重试'}
            print('自动备用已启用：'+descriptions.get(state.get('phase'),state.get('phase','unknown')))
            if state.get('observe_only'):
                print('当前仅观察，不会自动接管。')
            if not state.get('proxy',{}).get('compatible',True):
                print('当前代理/VPN出口未能核实，已阻止 LTE 自动接管。')
        return 0
    if os.geteuid()!=0:
        parser.error('此操作需要 macOS 管理员权限。')
    if args.action=='stop':
        state = alive()
        if not state:
            pid=orphan_engine()
            if pid:
                os.kill(pid,signal.SIGUSR1)
                deadline=time.monotonic()+30
                while orphan_engine() and time.monotonic()<deadline:
                    time.sleep(0.25)
                if orphan_engine():
                    print('上次 LTE 进程仍在清理，请查看日志。')
                    return 1
            print('自动 LTE 当前未运行。')
            return 0
        os.kill(state['pid'],signal.SIGUSR1)
        deadline=time.monotonic()+40
        while alive() and time.monotonic()<deadline:
            time.sleep(0.25)
        if alive():
            print('仍在清理，请查看 auto-state.json。')
            return 1
        print('自动备用 LTE 已停止。')
        return 0
    if args.action=='start':
        if alive():
            print('自动备用 LTE 已运行。')
            return 0
        directory=BASE/'logs'
        directory.mkdir(exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        with (directory/('auto-'+stamp+'.log')).open('w') as output:
            process=subprocess.Popen([sys.executable,str(BASE/'lte_auto.py'),'run']+
                (['--observe'] if args.observe else []),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+50
        while process.poll() is None and time.monotonic()<deadline:
            state=alive()
            if state and state.get('phase') in ('ready','standby','LTE','retrying','waiting_module'):
                print('自动备用 LTE 已启动：'+state['phase']+'。详见 auto-state.json。')
                return 0
            time.sleep(0.25)
        if process.poll() is None:
            process.send_signal(signal.SIGUSR1)
        print('自动备用启动未完成，查看 logs/auto-*.log。')
        return 1
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('其他 LTE 操作或自动管理程序正在运行。')
            return 1
        return run(args.observe,args.duration or (55 if args.action=='self-test' else 0),args.action=='self-test')


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        log(str(error))
        raise SystemExit(1)

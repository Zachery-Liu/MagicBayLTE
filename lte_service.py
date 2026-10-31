# SPDX-License-Identifier: AGPL-3.0-only
"""Install/manage the reviewed root-owned LTE supervisor. No actions on import."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parent
TARGET=Path('/Library/Application Support/MagicBayLTE')
PLIST=Path('/Library/LaunchDaemons/local.magicbay.lte.auto.plist')
LABEL='local.magicbay.lte.auto'
FILES=('lte_auto.py','failover_policy.py','magicbay_lte_managed','lte_helper.py','network_events.py','magicbay_network_watch')


def command(args):
    return subprocess.run(args,capture_output=True,text=True,timeout=60)


def definition():
    return {'Label':LABEL,'ProgramArguments':['/usr/bin/python3',str(TARGET/'lte_helper.py')],
            'WorkingDirectory':str(TARGET),'RunAtLoad':True,
            'KeepAlive':True,'ThrottleInterval':30,'ExitTimeOut':45,
            'StandardOutPath':str(TARGET/'logs/service.log'),
            'StandardErrorPath':str(TARGET/'logs/service.log'),
            'EnvironmentVariables':{'PYTHONUNBUFFERED':'1'}}


def verify_build():
    manifest=json.loads((BASE/'build-manifest.json').read_text())
    for name in FILES:
        if hashlib.sha256((BASE/name).read_bytes()).hexdigest()!=manifest['sha256'][name]:
            raise RuntimeError('程序与离线构建清单不同步，请先运行 build_offline.py。')
    return manifest


def hard_stop():
    command(['/bin/launchctl','disable','system/'+LABEL])
    command(['/bin/launchctl','bootout','system/'+LABEL])
    if (TARGET/'lte_auto.py').exists():
        result=command(['/usr/bin/python3',str(TARGET/'lte_auto.py'),'stop'])
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
    wait_unloaded()
    print('后台服务已停止。')


def wait_unloaded(timeout=15):
    # bootout can acknowledge removal while the old helper is still exiting.
    # Do not bootstrap the same label or replace code until launchd finishes.
    deadline=time.monotonic()+timeout
    while command(['/bin/launchctl','print','system/'+LABEL]).returncode==0:
        if time.monotonic()>=deadline:
            raise RuntimeError('旧后台服务尚未退出，已停止更新以避免新旧服务重叠。')
        time.sleep(0.1)


def helper_request(enabled):
    # Only the installed, root-owned helper client module is imported here.
    result=command(['/usr/bin/python3','-c',
        'import sys;sys.path.insert(0,'+repr(str(TARGET))+');import lte_helper;lte_helper.request('+repr(enabled)+')'])
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)


def stop():
    helper_request(False)
    print('LTE 已关闭；后台助手保留，之后启用无需再次授权。')


def start():
    if (TARGET/'control.sock').exists():
        helper_request(True)
        return
    if not PLIST.exists():
        install()
        return
    command(['/bin/launchctl','enable','system/'+LABEL])
    if command(['/bin/launchctl','print','system/'+LABEL]).returncode:
        result=command(['/bin/launchctl','bootstrap','system',str(PLIST)])
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        try:
            helper_request(True)
            return
        except RuntimeError:
            time.sleep(0.25)
    raise RuntimeError('后台助手尚未就绪，查看 logs/service.log。')


def wait_ready():
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        try:
            state=json.loads((TARGET/'helper-state.json').read_text())
            if state.get('phase')!='offline' and state.get('protocol_version')==1:
                os.kill(state['pid'],0)
                if (TARGET/'control.sock').exists():
                    print('后台助手已安装；日常启停 LTE 无需管理员密码。')
                    return
        except (OSError,ValueError,KeyError):
            pass
        time.sleep(0.25)
    raise RuntimeError('后台助手尚未就绪，查看 logs/service.log。')


def install():
    manifest=verify_build()
    if PLIST.exists():
        hard_stop()
    TARGET.mkdir(parents=True,exist_ok=True)
    (TARGET/'logs').mkdir(exist_ok=True)
    os.chown(TARGET,0,0);TARGET.chmod(0o755)
    os.chown(TARGET/'logs',0,0);(TARGET/'logs').chmod(0o755)
    for name in FILES:
        temporary=TARGET/(name+'.new')
        shutil.copyfile(BASE/name,temporary)
        os.chown(temporary,0,0)
        temporary.chmod(0o755 if name in ('magicbay_lte_managed','magicbay_network_watch') else 0o644)
        temporary.replace(TARGET/name)
    (TARGET/'installed-build.json').write_text(json.dumps(manifest,indent=2))
    temporary=PLIST.with_suffix('.new')
    temporary.write_bytes(plistlib.dumps(definition()))
    os.chown(temporary,0,0);temporary.chmod(0o644)
    temporary.replace(PLIST)
    command(['/bin/launchctl','enable','system/'+LABEL])
    result=command(['/bin/launchctl','bootstrap','system',str(PLIST)])
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    wait_ready()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','start','stop','status','uninstall'])
    args=parser.parse_args(argv)
    if args.action=='status':
        if (TARGET/'lte_auto.py').exists():
            return subprocess.call(['/usr/bin/python3',str(TARGET/'lte_auto.py'),'status'])
        print('自动备用 LTE 尚未安装。')
        return 0
    if args.action in ('install','uninstall') and os.geteuid()!=0:
        parser.error('安装或卸载需要 macOS 管理员权限。')
    if args.action=='uninstall':
        hard_stop()
        PLIST.unlink(missing_ok=True)
        for name in FILES:
            (TARGET/name).unlink(missing_ok=True)
        print('服务已卸载，历史日志保留于 '+str(TARGET/'logs'))
    else:
        globals()[args.action]()
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        print('自动备用 LTE 操作失败：'+str(error))
        raise SystemExit(1)

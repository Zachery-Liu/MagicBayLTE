# SPDX-License-Identifier: AGPL-3.0-only
"""Remove programs, reset enabled intent, clear runtime state; optionally remove logs."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import sys

BASE = Path('/Library/Application Support/MagicBayLTE')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove-logs', action='store_true', help='同时删除本地日志')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise SystemExit('请使用 sudo /usr/bin/python3 运行此卸载程序。')
    if Path(__file__).resolve().parent != BASE:
        raise SystemExit('请运行安装在系统后台目录中的卸载程序。')
    sys.path.insert(0, str(BASE))
    import lte_service
    lte_service.uninstall(remove_logs=args.remove_logs)
    (BASE / 'lte_service.py').unlink(missing_ok=True)
    app = Path('/Applications/Magic Bay LTE.app')
    if app.is_symlink():
        raise SystemExit('应用路径为符号链接，请手动检查；后台已经停止。')
    if app.exists():
        shutil.rmtree(app)
    subprocess.run(['/usr/sbin/pkgutil', '--forget', 'io.github.zachery-liu.magicbaylte'], check=False)
    print('已卸载，LTE 已重置为停用，运行状态已清理。')
    print(('对应源码保留于：' if args.remove_logs else '日志和对应源码保留于：') + str(BASE))


if __name__ == '__main__':
    main()

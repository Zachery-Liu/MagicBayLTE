# SPDX-License-Identifier: AGPL-3.0-only
"""Remove installed programs; preserve local logs, state and corresponding source."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

BASE = Path('/Library/Application Support/MagicBayLTE')


def main():
    if os.geteuid() != 0:
        raise SystemExit('请使用 sudo /usr/bin/python3 运行此卸载程序。')
    if Path(__file__).resolve().parent != BASE:
        raise SystemExit('请运行安装在系统后台目录中的卸载程序。')
    sys.path.insert(0, str(BASE))
    import lte_service
    lte_service.hard_stop()
    lte_service.PLIST.unlink(missing_ok=True)
    for name in lte_service.FILES + ('lte_service.py',):
        (BASE / name).unlink(missing_ok=True)
    app = Path('/Applications/Magic Bay LTE.app')
    if app.is_symlink():
        raise SystemExit('应用路径为符号链接，请手动检查；后台已经停止。')
    if app.exists():
        shutil.rmtree(app)
    subprocess.run(['/usr/sbin/pkgutil', '--forget', 'io.github.zachery-liu.magicbaylte'], check=False)
    print('已卸载。日志、状态与对应源码保留于：' + str(BASE))


if __name__ == '__main__':
    main()

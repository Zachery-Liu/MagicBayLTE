# SPDX-License-Identifier: AGPL-3.0-only
"""Build the native menu app. Does not start or change the LTE service."""
from pathlib import Path
import hashlib
import json
import plistlib
import subprocess
import tempfile
import shutil

BASE=Path(__file__).resolve().parent
APP=BASE/'build/Magic Bay LTE.app'


def run(args):
    subprocess.run(args,cwd=BASE,check=True)


def main():
    contents=APP/'Contents'
    (contents/'MacOS').mkdir(parents=True,exist_ok=True)
    (contents/'MacOS/MagicBayLTE').unlink(missing_ok=True)
    (contents/'Resources').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='magicbay-menu-build-') as temporary:
        directory=Path(temporary)
        run(['clang','-target','x86_64-apple-macosx13.0','-O2','-Wall','-Wextra','-Werror','-c','Telemetry.c','-o',str(directory/'Telemetry.o')])
        cache=BASE/'build/ModuleCache'
        cache.mkdir(exist_ok=True)
        run(['swiftc','-module-cache-path',str(cache),'-O','-swift-version','5','-target','x86_64-apple-macosx13.0',
             '-import-objc-header','Telemetry.h','Models.swift','AppModel.swift','Panel.swift','GitHubMark.swift','main.swift',
             str(directory/'Telemetry.o'),'-framework','AppKit','-framework','SwiftUI','-framework','IOKit','-framework','ServiceManagement',
             '-o',str(contents/'MacOS/Magic Bay LTE')])
        run(['swiftc','-module-cache-path',str(cache),'make_icon.swift','-o',str(directory/'make_icon')])
        run([str(directory/'make_icon'),str(directory/'AppIcon.iconset')])
        run(['/usr/bin/iconutil','-c','icns',str(directory/'AppIcon.iconset'),
             '-o',str(contents/'Resources/AppIcon.icns')])
    shutil.copyfile(BASE/'Assets/LICENSE-Octicons.txt',contents/'Resources/LICENSE-Octicons.txt')
    info={'CFBundleName':'Magic Bay LTE','CFBundleDisplayName':'Magic Bay LTE',
          'CFBundleIdentifier':'local.magicbay.lte.menu','CFBundleExecutable':'Magic Bay LTE',
          'CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.4.2','CFBundleVersion':'10',
          'CFBundleIconFile':'AppIcon','LSUIElement':True,'LSMinimumSystemVersion':'13.0',
          'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication'}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    run(['/usr/bin/codesign','--force','--sign','-','--identifier',info['CFBundleIdentifier'],str(APP)])
    run([str(contents/'MacOS/Magic Bay LTE'),'--self-test'])
    sources=['Telemetry.h','Telemetry.c','Models.swift','AppModel.swift','Panel.swift','GitHubMark.swift','main.swift','make_icon.swift','build_app.py','Assets/GitHubMark.svg','Assets/LICENSE-Octicons.txt']
    manifest={'app':str(APP),'backend_modified':False,
              'sha256':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in sources},
              'executable_sha256':hashlib.sha256((contents/'MacOS/Magic Bay LTE').read_bytes()).hexdigest()}
    (BASE/'build/app-build.json').write_text(json.dumps(manifest,indent=2))
    print(APP)


if __name__=='__main__':
    main()

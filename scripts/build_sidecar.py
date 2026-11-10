"""Freeze Python and bundle Node for Tauri. Run on the target OS."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('--target',default='x86_64-pc-windows-msvc' if sys.platform=='win32' else None)
args=parser.parse_args()
if not args.target:
    raise SystemExit('Pass --target with the Rust host tuple for this OS.')
if not (root/'app/web/index.html').is_file():
    raise SystemExit('Build the React frontend first: cd frontend && npm ci && npm run build')
node=shutil.which('node')
if not node: raise SystemExit('Install Node before building the desktop bundle.')
extension='.exe' if sys.platform=='win32' else ''
output=root/'frontend/src-tauri/binaries'
output.mkdir(parents=True,exist_ok=True)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--name','snacky-server-'+args.target,
    '--distpath',str(output),'--workpath',str(root/'scratch/sidecar-build'),'--specpath',str(root/'scratch'),
    '--paths',str(root),'--add-data',f'{root / "app/static"}:app/static','--add-data',f'{root / "app/web"}:app/web',
    '--collect-all','yt_dlp','--collect-all','yt_dlp_ejs','--collect-all','static_ffmpeg','--collect-all','gallery_dl',
    '--hidden-import','app.photo_probe','--hidden-import','uvicorn.logging','--hidden-import','uvicorn.loops.auto',
    '--hidden-import','uvicorn.protocols.http.auto','--hidden-import','uvicorn.protocols.websockets.auto',
    '--hidden-import','uvicorn.lifespan.on',str(root/'scripts/desktop_server.py')]
subprocess.run(command,cwd=root,check=True)
shutil.copy2(node,output/f'node-{args.target}{extension}')
print('Built Python media sidecar and bundled Node runtime.')

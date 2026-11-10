"""Verify a frozen Windows backend without global Python, Node or FFmpeg."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

from app.downloader import ensure_ffmpeg


def main():
    root=Path(__file__).resolve().parent.parent
    binaries=root/'frontend/src-tauri/binaries'
    backend=binaries/'snacky-server-x86_64-pc-windows-msvc.exe'
    node=binaries/'node-x86_64-pc-windows-msvc.exe'
    if not backend.is_file() or not node.is_file():
        raise SystemExit('Build the Windows sidecar first.')
    ensure_ffmpeg()
    with tempfile.TemporaryDirectory(prefix='sidecar-proof-',dir=root/'scratch') as directory:
        work=Path(directory)
        assert work.resolve().is_relative_to((root/'scratch').resolve())
        shutil.copy2(backend,work/'snacky-server.exe');shutil.copy2(node,work/'node.exe')
        downloads=work/'home/downloads';downloads.mkdir(parents=True)
        source=downloads/'සිංහල 🎵.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=purple:s=320x180:r=15','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True)
        env={**os.environ,'PATH':str(work)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32'),
             'HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1','NO_PROXY':'127.0.0.1,localhost'}
        # This invocation uses the bundled runtime, not an installed Node on PATH.
        assert subprocess.run([str(work/'node.exe'),'--version'],env=env,check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.startswith(b'v24.')
        probe=subprocess.run([str(work/'snacky-server.exe'),'-m','app.photo_probe'],input=json.dumps({'url':'https://example.com/post'}),text=True,encoding='utf-8',env=env,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        assert probe.returncode==0, probe.stderr
        assert json.loads(probe.stdout)=={'post':None}
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        client=build_opener(ProxyHandler({}))
        with (work/'backend.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(work/'snacky-server.exe'),'--port',str(port),'--home',str(work/'home'),'--managed'],env=env,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    assert process.poll() is None, (work/'backend.log').read_text(encoding='utf-8')
                    try:
                        with client.open(f'http://127.0.0.1:{port}/api/health',timeout=2) as response: health=json.load(response)
                        break
                    except OSError: time.sleep(.25)
                else: raise AssertionError('Frozen backend did not become ready')
                assert health['version']=='3.0.0' and health['mode']=='local'
                with client.open(f'http://127.0.0.1:{port}/',timeout=5) as response: assert b'/assets/' in response.read()
                url=f'http://127.0.0.1:{port}/api/download-file?filename={quote(source.name)}'
                with client.open(url,timeout=5) as response:
                    assert response.read()==source.read_bytes()
                    assert int(response.headers['Content-Length'])==source.stat().st_size
                    assert 'filename*=UTF-8' in response.headers['Content-Disposition']
                from urllib.request import Request
                with client.open(Request(url,headers={'Range':'bytes=0-127'}),timeout=5) as response:
                    assert response.status==206 and response.read()==source.read_bytes()[:128]
            finally:
                if process.poll() is None:
                    try:
                        process.stdin.write(b'shutdown\n');process.stdin.flush();process.stdin.close()
                        process.wait(timeout=20)
                    except (OSError,subprocess.TimeoutExpired):
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                        process.wait(timeout=10)
                        raise AssertionError('Managed backend did not stop gracefully')
                assert process.returncode==0
        try: client.open(f'http://127.0.0.1:{port}/api/health',timeout=1)
        except OSError: pass
        else: raise AssertionError('A desktop child server survived shutdown')
    print('PASS: offline frozen backend, React, Unicode/range attachments, gallery-dl, bundled Node/FFmpeg, graceful child shutdown and temporary-file cleanup')


if __name__=='__main__': main()

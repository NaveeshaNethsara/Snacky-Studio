"""Tauri's loopback Python sidecar; also dispatches isolated photo probes."""
import argparse
import os
import sys
import threading
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    if sys.argv[1:3] == ['-m','app.photo_probe']:
        import runpy
        runpy.run_module('app.photo_probe',run_name='__main__')
        return
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--managed',action='store_true',help='Exit when the desktop shell closes its control pipe')
    args=parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use a local unprivileged port')
    os.environ['SNACKY_MODE']='local'
    os.environ['SNACKY_DATA_DIR']=str(args.home / 'data')
    os.environ['SNACKY_DOWNLOADS_DIR']=str(args.home / 'downloads')
    # The desktop bundle places Node beside the Python sidecar.
    os.environ['PATH']=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH','')
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    import uvicorn
    from app.main import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(),host='127.0.0.1',port=args.port,log_level='warning'))
    if args.managed:
        def watch_shell():
            for line in sys.stdin:
                if line.strip() == 'shutdown':
                    break
            # EOF also closes the server if the desktop shell unexpectedly exits.
            server.should_exit = True
        threading.Thread(target=watch_shell,name='desktop-control',daemon=True).start()
    server.run()


if __name__ == '__main__':
    main()

import sys
import os
import socket
import webbrowser
import threading
import time
import json
from urllib.error import URLError
from urllib.request import urlopen


def find_running_app(ports=None):
    """Reuse a healthy current app instead of recovering another server's jobs."""
    for port in ports if ports is not None else [8126, 8125, *range(8000, 8020)]:
        url = f"http://127.0.0.1:{port}"
        try:
            with urlopen(url + "/api/health", timeout=.4) as response:
                health = json.load(response)
            if health.get("application") == "snacky-studio" and health.get("status") == "ok":
                return url
        except (URLError, OSError, ValueError):
            continue
    return None

def find_available_port(start_port=8000, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available local port between {start_port} and {start_port + max_attempts - 1}.")

def open_browser(url):
    for _ in range(150):
        try:
            with urlopen(f"{url}/api/health", timeout=.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (URLError, OSError):
            pass
        time.sleep(.2)
    print(f"Open {url} once the server has finished starting.")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    import argparse
    from app.config import Settings

    parser = argparse.ArgumentParser(description="Start your local Snacky Studio workspace.")
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser")
    args = parser.parse_args()

    if existing := find_running_app():
        print(f" [+] Snacky Studio is already running at: {existing}")
        if not args.no_browser:
            webbrowser.open(existing)
        sys.exit(0)

    port = find_available_port(8000)
    url = f"http://127.0.0.1:{port}"

    print("=" * 70)
    print(" [>>] Snacky Studio - Universal Video Downloader")
    print(" [*] YouTube | Instagram Reels | TikTok | Facebook Reels (MP4 & MP3)")
    print("=" * 70)
    print(f" [+] Local Web UI running at: {url}")
    print(f" [+] Downloads Directory: {Settings().downloads_dir}")
    if not args.no_browser:
        print(" [+] Browser opens when the server is ready...")
    print("=" * 70)

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")

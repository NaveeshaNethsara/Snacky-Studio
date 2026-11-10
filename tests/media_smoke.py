"""Exercise real yt-dlp, FFmpeg, and ffprobe with a generated one-second clip.

Run from the project root: python -m tests.media_smoke
Only a temporary localhost media server is used; nothing goes to a third party.
"""
import functools
import json
import shutil
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from app.downloader import download_media, ensure_ffmpeg, extract_video_info


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    ensure_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="snacky-smoke-") as directory:
        root = Path(directory)
        source = root / "සිංහල 🎵.mp4"
        outputs = root / "downloads"
        outputs.mkdir()
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x7856ab:s=320x180:r=15",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/{quote(source.name)}"
            info = extract_video_info(url)
            # A direct MP4 URL can have no resolution metadata; don't invent one.
            assert info["qualities"][0]["id"] == "best", info
            for media_format, quality in [("mp4", "best"), ("mp3", "320")]:
                states = []
                result = download_media(str(uuid4()), url, media_format, quality, outputs,
                                        lambda **update: states.append(update), threading.Event())
                output = outputs / result["filename"]
                probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(output)], check=True, capture_output=True, text=True, encoding="utf-8")
                streams = json.loads(probe.stdout)["streams"]
                if media_format == "mp4":
                    assert {stream["codec_type"] for stream in streams} == {"video", "audio"}, streams
                else:
                    assert streams[0]["codec_name"] == "mp3", streams
                    assert int(streams[0]["bit_rate"]) == 320000, streams
                assert output.stat().st_size > 0
                assert not list((outputs / ".work").iterdir())
                print(f"PASS: {media_format.upper()} · real yt-dlp + FFmpeg · Unicode filename · {output.stat().st_size} bytes")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()

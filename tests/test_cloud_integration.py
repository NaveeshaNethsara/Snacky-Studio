"""Opt-in proof with real PostgreSQL, Redis, Celery and S3-compatible storage.

Uses a generated clip served on loopback, never an external media platform.
The CI cloud job supplies isolated containers and enables this suite.
"""
import functools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.cloud_store import CloudJobStore
from app.config import Settings
from app.downloader import ensure_ffmpeg
from app.jobs import QueueFullError
from app.main import create_app
from app.storage import S3MediaStorage

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv('SNACKY_INTEGRATION') != '1', reason='Requires isolated PostgreSQL, Redis and S3 services')]


@pytest.fixture(scope='module')
def infrastructure(tmp_path_factory):
    settings = Settings(mode='cloud',data_dir=tmp_path_factory.mktemp('cloud-data'),downloads_dir=tmp_path_factory.mktemp('cloud-work'))
    settings.prepare()
    command.upgrade(Config('alembic.ini'), 'head')
    store = CloudJobStore(settings.database_url)
    storage = S3MediaStorage(settings,store)
    for attempt in range(30):
        try:
            storage.client.create_bucket(Bucket=settings.s3_bucket)
            break
        except storage.client.exceptions.BucketAlreadyOwnedByYou:
            break
        except Exception:
            if attempt == 29: raise
            time.sleep(2)
    yield settings,store,storage
    store.close()


def test_postgresql_admission_serializes_independent_api_repositories(infrastructure):
    settings,store,_ = infrastructure
    other = CloudJobStore(settings.database_url)
    barrier = threading.Barrier(2)
    def submit(repo):
        barrier.wait()
        try: return repo.create_job('https://youtu.be/test','mp4','best',0,'Integration admission',1)
        except QueueFullError: return None
    try:
        with ThreadPoolExecutor(2) as threads:
            results = list(threads.map(submit,[store,other]))
        assert sum(value is not None for value in results) == 1
        store.cancel(next(value for value in results if value))
    finally: other.close()


def test_real_celery_worker_publishes_media_for_two_api_replicas(infrastructure,tmp_path):
    settings,store,storage = infrastructure
    ensure_ffmpeg()
    source=tmp_path/'source.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=purple:s=320x180:r=15',
                    '-f','lavfi','-i','sine=frequency=440','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    env={**os.environ,'SNACKY_MODE':'cloud','SNACKY_DOWNLOADS_DIR':str(tmp_path/'worker'),'SNACKY_DATA_DIR':str(tmp_path/'worker-data')}
    with (tmp_path/'celery.log').open('w',encoding='utf-8') as log:
        worker=subprocess.Popen([sys.executable,'-m','celery','-A','app.worker:celery_app','worker','--pool=solo','--concurrency=1','--loglevel=WARNING'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            # Same secrets and shared SQL; either API can observe/save a worker's output.
            with TestClient(create_app(settings),base_url=settings.public_origin) as first, TestClient(create_app(settings),base_url=settings.public_origin) as second:
                assert first.post('/api/session/login',json={'password':settings.cloud_password}).status_code == 200
                second.cookies.update(first.cookies)
                job = store.create_job(f'http://127.0.0.1:{server.server_port}/source.mp4','mp3','320',0,'සිංහල 🎵 integration',100)
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    task=second.get(f'/api/progress/{job}').json()
                    if task['status'] in {'completed','error'}: break
                    assert worker.poll() is None, 'Celery worker exited; inspect its log'
                    time.sleep(.25)
                assert task['status']=='completed', task.get('error') or task['status']
                assert first.get(f'/api/progress/{job}').json()['filename'] == task['filename']
                response=second.get(f'/api/file/{job}',follow_redirects=False)
                assert response.status_code==307
                with urlopen(response.headers['location'],timeout=10) as download:
                    data=download.read()
                    assert int(download.headers['Content-Length']) == len(data) == task['size_bytes']
                    assert 'filename*=UTF-8' in download.headers['Content-Disposition']
                output=tmp_path/'saved.mp3';output.write_bytes(data)
                probe=json.loads(subprocess.run([shutil.which('ffprobe'),'-v','error','-show_streams','-of','json',str(output)],check=True,capture_output=True).stdout)
                assert probe['streams'][0]['codec_name']=='mp3'
                assert int(probe['streams'][0]['bit_rate'])==320000
                assert not list((tmp_path/'worker').iterdir())
                storage.delete(task['filename'])
                assert second.get(f'/api/file/{job}',follow_redirects=False).status_code==404
        finally:
            worker.terminate()
            try: worker.wait(timeout=15)
            except subprocess.TimeoutExpired: worker.kill();worker.wait()
            server.shutdown();server.server_close();thread.join(timeout=2)

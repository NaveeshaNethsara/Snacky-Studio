"""Shared-state, dispatch, fencing, cancellation, storage and access boundaries."""
import threading
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import boto3
import fakeredis
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.auth import make_session, valid_session
from app.cloud_store import CloudJobStore
from app.config import Settings
from app.jobs import DownloadCancelled, QueueFullError
from app.main import create_app
from app.storage import S3MediaStorage
from app.worker import execute_job


@pytest.fixture
def store(tmp_path):
    value = CloudJobStore(f"sqlite:///{tmp_path / 'shared.sqlite'}", initialize=True)
    yield value
    value.close()


def add(store, title="සිංහල 🎵"):
    return store.create_job("https://youtu.be/test", "mp4", "720", 0, title, 100)


def test_queue_admission_is_atomic_across_two_api_repositories(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.sqlite'}"
    first, second = CloudJobStore(url, initialize=True), CloudJobStore(url)
    barrier = threading.Barrier(2)
    admitted, rejected = [], []
    def submit(repo):
        barrier.wait()
        try: admitted.append(repo.create_job("https://youtu.be/test", "mp4", "720", 0, "Example", 1))
        except QueueFullError: rejected.append(True)
    workers = [threading.Thread(target=submit,args=(repo,)) for repo in (first,second)]
    for worker in workers: worker.start()
    for worker in workers: worker.join()
    assert len(admitted) == len(rejected) == 1
    first.close(); second.close()


def test_failed_dispatch_keeps_job_durable_for_retry(store):
    job = add(store)
    def unavailable(_): raise ConnectionError("Redis unavailable")
    with pytest.raises(ConnectionError): store.dispatch_due(unavailable)
    sent = []
    assert store.dispatch_due(sent.append) == 1
    assert sent == [job]
    assert store.dispatch_due(sent.append) == 0


def test_redelivery_cannot_run_an_owned_or_completed_job(store):
    job = add(store)
    assert store.claim(job,"worker-one",120)
    assert store.claim(job,"worker-two",120) is None
    store.worker_update(job,"worker-one",120,status="completed",filename="one.mp4")
    assert store.claim(job,"worker-two",120) is None


def test_expired_lease_fences_the_previous_worker(store):
    job = add(store)
    assert store.claim(job,"old",-.1)
    assert store.claim(job,"new",120)
    assert not store.heartbeat(job,"old",120)
    assert store.worker_update(job,"old",120,status="completed") is None
    assert store.worker_update(job,"new",120,status="completed")["status"] == "completed"


def test_queued_cancel_is_terminal_and_running_cancel_is_durable(store):
    queued, running = add(store), add(store)
    assert store.cancel(queued)["status"] == "cancelled"
    assert store.claim(queued,"worker",120) is None
    store.claim(running,"worker",120)
    assert store.cancel(running)["status"] == "cancelling"
    assert store.worker_update(running,"worker",120,status="downloading")["status"] == "cancelling"


@pytest.fixture
def storage(tmp_path, store, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID","test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY","test-secret")
    settings = Settings(downloads_dir=tmp_path / 'work', data_dir=tmp_path / 'data')
    settings.prepare()
    with mock_aws():
        boto3.client('s3',region_name='us-east-1').create_bucket(Bucket=settings.s3_bucket)
        yield settings, S3MediaStorage(settings,store)


def engine(job_id,url,media_format,quality,directory,progress,cancel,**options):
    progress(status="downloading",progress=45)
    name = f"සිංහල 🎵 [{job_id}].mp4"
    (directory/name).write_bytes(b"complete test file")
    return {"filename":name,"title":"සිංහල 🎵"}


def test_worker_publishes_once_and_api_can_save_without_worker_disk(store,storage):
    settings, s3 = storage
    job = add(store)
    execute_job(job,settings,store,s3,engine=engine)
    task = store.get(job)
    assert task["status"] == "completed"
    assert task["size_bytes"] == len(b"complete test file")
    assert not list(settings.downloads_dir.iterdir())
    result = s3.client.get_object(Bucket=settings.s3_bucket,Key=task["storage_key"])
    assert result['Body'].read() == b"complete test file"
    response = s3.response(task)
    assert response.status_code == 307
    assert parse_qs(urlsplit(response.headers['location']).query)['response-content-disposition'][0].encode('ascii')
    before = task["storage_key"]
    execute_job(job,settings,store,s3,engine=lambda *args,**kwargs: pytest.fail('duplicate worker ran'))
    assert store.get(job)["storage_key"] == before


def test_upload_failure_never_marks_job_completed(store,storage,monkeypatch):
    settings,s3 = storage
    monkeypatch.setattr(s3,'publish',lambda *args: (_ for _ in ()).throw(ConnectionError('S3 unavailable')))
    job = add(store)
    execute_job(job,settings,store,s3,engine=engine)
    assert store.get(job)["status"] == "error"
    assert not store.get(job).get('storage_key')


def test_photo_index_reaches_distributed_worker(store,storage):
    settings,s3 = storage
    job = store.create_job('https://www.facebook.com/photo?fbid=123','photo','best',2,'A photo',100)
    def photo_engine(*args,**kwargs):
        assert kwargs['photo_index'] == 2
        return engine(*args,**kwargs)
    execute_job(job,settings,store,s3,engine=photo_engine)
    assert store.get(job)['status'] == 'completed'


def test_private_session_rejects_tampering_and_expiration():
    secret = 'x'*32
    token = make_session(secret)
    assert valid_session(token,secret)
    assert not valid_session(token+'a',secret)
    assert not valid_session(make_session(secret,now=time.time()-30000),secret)
    assert not valid_session(token,'another-secret')


def test_cloud_configuration_requires_database_and_secrets():
    with pytest.raises(ValueError): Settings(mode='cloud').validate()
    with pytest.raises(ValueError): Settings(mode='cloud',database_url='postgresql://test',cloud_password='short').validate()


def test_cloud_requires_login_and_blocks_cross_origin_mutations(tmp_path,store,storage,monkeypatch):
    settings,s3 = storage
    settings = replace(settings,mode='cloud',database_url='postgresql+psycopg://unused',cloud_password='a-private-password',session_secret='s'*32)
    class Manager:
        def __init__(self,*args): self.store=store;self.redis=fakeredis.FakeRedis()
        def owns(self,_): return True
        def shutdown(self): pass
    monkeypatch.setattr('app.cloud.CloudDownloadManager',Manager)
    monkeypatch.setattr('app.main.S3MediaStorage',lambda *args:s3)
    with TestClient(create_app(settings),base_url="http://localhost:8080") as client:
        assert client.get('/api/history').status_code == 401
        assert client.get('/api/session').json()['authenticated'] is False
        assert client.post('/api/session/login',json={'password':'wrong'}).status_code == 401
        assert client.post('/api/session/login',json={'password':settings.cloud_password}).status_code == 200
        assert client.get('/api/history').status_code == 200
        assert client.post('/api/open-folder').status_code == 400
        assert client.post('/api/download',json={'url':'https://example.com/media'},headers={'origin':'https://evil.example'}).status_code == 403
        assert client.post('/api/download',json={'url':'https://example.com/media'}).status_code == 400
        assert client.post('/api/session/logout').status_code == 200
        assert client.get('/api/tasks').status_code == 401


def test_login_rate_limit_is_shared(tmp_path,store,storage,monkeypatch):
    settings,s3 = storage
    settings = replace(settings,mode='cloud',database_url='postgresql+psycopg://unused',cloud_password='a-private-password',session_secret='s'*32)
    class Manager:
        def __init__(self,*args): self.store=store;self.redis=fakeredis.FakeRedis()
        def owns(self,_): return True
        def shutdown(self): pass
    monkeypatch.setattr('app.cloud.CloudDownloadManager',Manager)
    monkeypatch.setattr('app.main.S3MediaStorage',lambda *args:s3)
    with TestClient(create_app(settings),base_url="http://localhost:8080") as client:
        for _ in range(10): assert client.post('/api/session/login',json={'password':'wrong'}).status_code == 401
        assert client.post('/api/session/login',json={'password':'wrong'}).status_code == 429

"""Check the assembled gateway, shared private sessions and SSE after Compose up."""
import http.cookiejar
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor


def main():
    values = dict(line.split('=',1) for line in Path('.env.cloud').read_text().splitlines() if line and not line.startswith('#'))
    origin = values['SNACKY_PUBLIC_ORIGIN']
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with client.open(origin+'/api/health',timeout=10) as response:
        health=json.load(response)
        assert health['version']=='3.0.0' and health['mode']=='cloud'
    try: client.open(origin+'/api/tasks',timeout=10)
    except HTTPError as error: assert error.code==401
    else: raise AssertionError('Private tasks were exposed without a session')
    request=Request(origin+'/api/session/login',data=json.dumps({'password':values['SNACKY_CLOUD_PASSWORD']}).encode(),headers={'Content-Type':'application/json','Origin':origin})
    with client.open(request,timeout=10) as response: assert json.load(response)['authenticated']
    for _ in range(8):
        # Gateway round-robin connects to both API replicas using the same signed session.
        with client.open(origin+'/api/tasks',timeout=10) as response: assert isinstance(json.load(response)['tasks'],list)
    with client.open(origin+'/api/stream-tasks',timeout=10) as response:
        assert response.headers['Content-Type'].startswith('text/event-stream')
        while True:
            line=response.readline().decode()
            if line.startswith('data: '):
                assert isinstance(json.loads(line[6:])['tasks'],list)
                break
            assert line, 'SSE ended without an initial snapshot'
    with client.open(origin,timeout=10) as response: assert b'/assets/' in response.read()
    print('PASS: assembled private cloud, React assets, replica sessions and SSE')


if __name__=='__main__': main()

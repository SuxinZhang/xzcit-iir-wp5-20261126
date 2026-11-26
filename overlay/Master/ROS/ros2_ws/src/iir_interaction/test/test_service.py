"""Exercise the authenticated audio API.
验证鉴权音频接口。
"""
import unittest
from aiohttp.test_utils import TestClient, TestServer
from iir_interaction.service import create_app


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(create_app('secret', 'http://localhost:8889', 'media', 'sink', 'rtsp://localhost:8554', 'model')))
        await self.client.start_server()
        self.auth = {'Authorization': 'Bearer secret'}

    async def asyncTearDown(self):
        await self.client.close()

    async def test_authentication_and_owner(self):
        response = await self.client.get('/status')
        self.assertEqual(response.status, 401)
        response = await self.client.post('/sessions', headers=self.auth, json={'owner': 'a', 'mode': 'video'})
        self.assertEqual(response.status, 200)
        session = (await response.json())['session_id']
        response = await self.client.delete('/sessions/' + session + '?owner=b', headers=self.auth)
        self.assertEqual(response.status, 403)
        response = await self.client.delete('/sessions/' + session + '?owner=a', headers=self.auth)
        self.assertEqual(response.status, 200)

    async def test_audio_reservation_conflict(self):
        for owner in ('a', 'b'):
            response = await self.client.post('/sessions', headers=self.auth, json={'owner': owner, 'mode': 'intercom'})
            self.assertEqual(response.status, 200 if owner == 'a' else 409)

class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_exit_releases_reservation_and_records_failure(self):
        import asyncio
        import sys
        from iir_interaction.service import AudioService
        service = AudioService('http://localhost', 'token', 'sink', 'rtsp://localhost', 'model')
        await service.reserve('a', 'intercom')
        service.sessions['a'] = {'state': 'reserved'}
        await service.spawn('a', sys.executable, '-c', 'import time; time.sleep(.3)')
        await asyncio.sleep(.3)
        self.assertIsNone(service.arbiter.owner)
        self.assertEqual(service.sessions['a']['state'], 'failed')

    async def test_preemption_stops_actual_process(self):
        import sys
        from iir_interaction.service import AudioService
        service = AudioService('http://localhost', 'token', 'sink', 'rtsp://localhost', 'model')
        await service.reserve('a', 'intercom')
        await service.spawn('a', sys.executable, '-c', 'import time; time.sleep(30)')
        process = service.processes['a']
        async with service.lock:
            await service.reserve('b', 'sos')
        self.assertIsNotNone(process.returncode)
        self.assertEqual(service.arbiter.owner.request_id, 'b')

class OfferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import os
        import tempfile
        from aiohttp import web
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = os.environ['PATH']
        executable = os.path.join(self.tmp.name, 'gst-launch-1.0')
        with open(executable, 'w') as f:
            f.write('#!/bin/sh\nsleep 30\n')
        os.chmod(executable, 0o755)
        os.environ['PATH'] = self.tmp.name + ':' + self.old_path
        async def offer(request):
            return web.Response(status=201, text='answer', headers={'Location': '/resource/1'})
        async def remove(request):
            return web.Response(status=204)
        app = web.Application()
        app.router.add_post('/platform_voice/whip', offer)
        app.router.add_delete('/resource/1', remove)
        self.media = TestServer(app)
        await self.media.start_server()
        self.client = TestClient(TestServer(create_app('secret', str(self.media.make_url('/')), 'media', 'sink', 'rtsp://localhost:8554', 'model')))
        await self.client.start_server()
        self.auth = {'Authorization': 'Bearer secret'}

    async def asyncTearDown(self):
        import os
        await self.client.close()
        await self.media.close()
        os.environ['PATH'] = self.old_path
        self.tmp.cleanup()

    async def test_duplicate_offer_and_preemption(self):
        r = await self.client.post('/sessions', headers=self.auth, json={'owner': 'a', 'mode': 'intercom'})
        sid = (await r.json())['session_id']
        payload = {'owner': 'a', 'kind': 'publish', 'sdp': 'offer'}
        r = await self.client.post(f'/sessions/{sid}/offer', headers=self.auth, json=payload)
        self.assertEqual(r.status, 200)
        r = await self.client.get('/status', headers=self.auth)
        self.assertEqual((await r.json())['playback_state'], 'reserved')
        r = await self.client.post(f'/sessions/{sid}/activate', headers=self.auth, json={'owner': 'b'})
        self.assertEqual(r.status, 403)
        r = await self.client.post(f'/sessions/{sid}/activate', headers=self.auth, json={'owner': 'a'})
        self.assertEqual(r.status, 200)
        r = await self.client.post(f'/sessions/{sid}/activate', headers=self.auth, json={'owner': 'a'})
        self.assertEqual(r.status, 409)
        r = await self.client.post(f'/sessions/{sid}/offer', headers=self.auth, json=payload)
        self.assertEqual(r.status, 409)
        r = await self.client.get('/status', headers=self.auth)
        status = await r.json()
        self.assertEqual(status['playback_state'], 'starting')
        self.assertEqual(status['owner']['request_id'], sid)
        r = await self.client.post('/sos', headers=self.auth, json={'active': True})
        self.assertEqual(r.status, 200)
        r = await self.client.get('/status', headers=self.auth)
        self.assertEqual((await r.json())['sessions'][sid]['state'], 'interrupted')
        r = await self.client.post(f'/sessions/{sid}/activate', headers=self.auth, json={'owner': 'a'})
        self.assertEqual(r.status, 409)

    async def test_activation_requires_publish_offer(self):
        r = await self.client.post('/sessions', headers=self.auth, json={'owner': 'a', 'mode': 'intercom'})
        sid = (await r.json())['session_id']
        r = await self.client.post(f'/sessions/{sid}/activate', headers=self.auth, json={'owner': 'a'})
        self.assertEqual(r.status, 409)

class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_sos_failed_speech_keeps_reservation_until_clear(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            piper = os.path.join(directory, 'piper')
            with open(piper, 'w') as stream:
                stream.write('#!/bin/sh\nexit 2\n')
            os.chmod(piper, 0o755)
            old = os.environ['PATH']
            os.environ['PATH'] = directory + ':' + old
            client = TestClient(TestServer(create_app('secret', 'http://localhost', 'token', 'sink', 'rtsp://localhost', 'model')))
            await client.start_server()
            try:
                auth = {'Authorization': 'Bearer secret'}
                await client.post('/sos', headers=auth, json={'active': True})
                response = await client.post('/speak', headers=auth, json={'source': 'sos', 'event': 'sos'})
                self.assertEqual(response.status, 502)
                response = await client.get('/status', headers=auth)
                self.assertEqual((await response.json())['owner']['source'], 'sos')
                await client.post('/sos', headers=auth, json={'active': False})
                response = await client.get('/status', headers=auth)
                self.assertIsNone((await response.json())['owner'])
            finally:
                await client.close()
                os.environ['PATH'] = old

class MediaConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        from aiohttp import web
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.posts, self.deletes, self.fail_delete = 0, 0, False
        async def offer(request):
            self.posts += 1
            if self.posts == 1:
                self.entered.set()
                await self.release.wait()
            return web.Response(status=201, text='answer', headers={'Location': f'/resource/{self.posts}'})
        async def remove(request):
            self.deletes += 1
            if self.fail_delete:
                self.fail_delete = False
                return web.Response(status=500)
            return web.Response(status=204)
        app = web.Application()
        app.router.add_post('/camera/whep', offer)
        app.router.add_post('/platform_voice/whip', offer)
        app.router.add_delete('/resource/{id}', remove)
        self.media = TestServer(app)
        await self.media.start_server()
        from aiohttp.web_runner import AppRunner
        class ProductionTestServer(TestServer):
            async def _make_runner(self, **kwargs):
                kwargs['handler_cancellation'] = False
                return AppRunner(self.app, **kwargs)
        self.client = TestClient(ProductionTestServer(create_app('secret', str(self.media.make_url('/')), 'media', 'sink', 'rtsp://localhost', 'model')))
        await self.client.start_server()
        self.auth = {'Authorization': 'Bearer secret'}

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()
        await self.media.close()

    async def create(self, owner, mode):
        response = await self.client.post('/sessions', headers=self.auth, json={'owner': owner, 'mode': mode})
        self.assertEqual(response.status, 200)
        return (await response.json())['session_id']

    async def test_sos_does_not_wait_for_offer_and_second_offer_waits(self):
        import asyncio
        sid = await self.create('a', 'intercom')
        old = asyncio.create_task(self.client.post(f'/sessions/{sid}/offer', headers=self.auth, json={'owner': 'a', 'kind': 'publish', 'sdp': 'x'}))
        await self.entered.wait()
        response = await asyncio.wait_for(self.client.post('/sos', headers=self.auth, json={'active': True}), .5)
        self.assertEqual(response.status, 200)
        video = await self.create('b', 'video')
        new = asyncio.create_task(self.client.post(f'/sessions/{video}/offer', headers=self.auth, json={'owner': 'b', 'kind': 'camera', 'sdp': 'x'}))
        await asyncio.sleep(.05)
        self.assertEqual(self.posts, 1)
        self.release.set()
        self.assertEqual((await old).status, 409)
        self.assertEqual((await new).status, 200)
        self.assertEqual(self.deletes, 1)

    async def test_delete_failure_preserves_session_for_retry(self):
        self.release.set()
        sid = await self.create('a', 'video')
        response = await self.client.post(f'/sessions/{sid}/offer', headers=self.auth, json={'owner': 'a', 'kind': 'camera', 'sdp': 'x'})
        self.assertEqual(response.status, 200)
        self.fail_delete = True
        response = await self.client.delete(f'/sessions/{sid}?owner=a', headers=self.auth)
        self.assertEqual(response.status, 502)
        response = await self.client.delete(f'/sessions/{sid}?owner=a', headers=self.auth)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.deletes, 2)

    async def test_disconnected_offer_then_close_owner_cleans_resource(self):
        import asyncio
        import urllib.parse
        sid = await self.create('a', 'video')
        url = self.client.make_url(f'/sessions/{sid}/offer')
        reader, writer = await asyncio.open_connection(url.host, url.port)
        body = b'{"owner":"a","kind":"camera","sdp":"x"}'
        writer.write(f'POST {url.path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer secret\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
        await writer.drain()
        await self.entered.wait()
        writer.close()
        await writer.wait_closed()
        close = asyncio.create_task(self.client.post('/owners/a/close', headers=self.auth))
        await asyncio.sleep(.05)
        self.release.set()
        self.assertEqual((await close).status, 200)
        self.assertEqual(self.deletes, 1)

class OwnerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_owner_cannot_create_late_session(self):
        client = TestClient(TestServer(create_app('secret', 'http://localhost', 'token', 'sink', 'rtsp://localhost', 'model')))
        await client.start_server()
        try:
            auth = {'Authorization': 'Bearer secret'}
            response = await client.post('/owners/generation-a/close', headers=auth)
            self.assertEqual(response.status, 200)
            response = await client.post('/sessions', headers=auth, json={'owner': 'generation-a', 'mode': 'video'})
            self.assertEqual(response.status, 409)
            response = await client.post('/sessions', headers=auth, json={'owner': 'generation-b', 'mode': 'video'})
            self.assertEqual(response.status, 200)
        finally:
            await client.close()

class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_failure_still_stops_other_process_and_closes_client(self):
        from unittest.mock import AsyncMock
        from iir_interaction.service import AudioService, Failure
        service = AudioService('http://localhost', 'token', 'sink', 'rtsp://localhost', 'model')
        service.sessions = {'a': {'state': 'reserved', 'locations': []}, 'b': {'state': 'reserved', 'locations': []}}
        service.processes = {'a': object(), 'b': object()}
        stopped = []
        async def stop(rid):
            stopped.append(rid)
            if rid == 'a':
                raise Failure(503, 'stop failed')
            service.processes.pop(rid, None)
        service.stop = stop
        service.client = type('Client', (), {'close': AsyncMock()})()
        with self.assertRaises(Failure):
            await service.shutdown(None)
        self.assertIn('b', stopped)
        service.client.close.assert_awaited_once()

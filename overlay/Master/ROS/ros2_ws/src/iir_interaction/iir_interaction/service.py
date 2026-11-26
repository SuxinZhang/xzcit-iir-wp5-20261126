"""Run the authenticated local audio service.
运行经过鉴权的本机音频服务。
"""
import asyncio
import os
import tempfile
import uuid
from urllib.parse import urljoin

import aiohttp
from aiohttp import web

from .arbitration import AudioArbiter
from .contracts import AudioRequest
from .voice import announcement_for, command_from_text


class Failure(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except Failure as exc:
        return web.json_response({'error': exc.message}, status=exc.status)
    except (ValueError, KeyError, TypeError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
        return web.json_response({'error': str(exc)}, status=502)


class AudioService:
    def __init__(self, base, token, sink, rtsp, model):
        self.base, self.auth = base.rstrip('/') + '/', aiohttp.BasicAuth('iir-interaction', token)
        self.sink, self.rtsp, self.model = sink, rtsp.rstrip('/'), model
        self.arbiter, self.lock = AudioArbiter(), asyncio.Lock()
        self.sessions, self.processes = {}, {}
        self.closed_owners = set()
        self.blocked = None
        self.media_lock = asyncio.Lock()
        self.sos = False
        self.speech_busy = set()
        self.command_queue = asyncio.Queue()
        self.client = None

    async def start(self, app):
        self.client = aiohttp.ClientSession(auth=self.auth, timeout=aiohttp.ClientTimeout(total=2))

    async def shutdown(self, app):
        failures = []
        ready = []
        failed_stops = set()
        try:
            async with self.lock:
                for sid in list(self.sessions):
                    try:
                        await self.close(sid)
                        ready.append(sid)
                    except (Failure, OSError) as exc:
                        failed_stops.add(sid)
                        failures.append(f'{sid}: {exc}')
                for rid in list(self.processes):
                    if rid in failed_stops:
                        continue
                    try:
                        await self.stop(rid)
                    except (Failure, OSError) as exc:
                        failures.append(f'{rid}: {exc}')
            async with self.media_lock:
                for sid in ready:
                    try:
                        await self.cleanup_session(sid)
                    except Failure as exc:
                        failures.append(f'{sid}: {exc}')
            if failures:
                raise Failure(503, '; '.join(failures))
        finally:
            await self.client.close()

    async def stop(self, rid):
        proc = self.processes.get(rid)
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                self.blocked = 'audio process did not stop'
                raise Failure(503, self.blocked)
        self.processes.pop(rid, None)

    async def reserve(self, rid, source):
        if self.blocked:
            raise Failure(503, self.blocked)
        result = self.arbiter.acquire(AudioRequest(rid, source))
        if not result.accepted:
            raise Failure(409, 'audio output is reserved')
        if result.interrupted:
            try:
                await self.stop(result.interrupted.request_id)
            except Failure:
                self.blocked = 'audio process did not stop'
                raise
            old = self.sessions.get(result.interrupted.request_id)
            if old:
                old['state'] = 'interrupted'

    async def watch(self, rid, proc, persistent=False):
        code = await proc.wait()
        async with self.lock:
            if self.processes.get(rid) is not proc:
                return
            self.processes.pop(rid, None)
            session = self.sessions.get(rid)
            if session:
                session['state'] = 'failed'
                session['error'] = f'audio process exited: {code}'
            if not persistent:
                self.arbiter.release(rid)

    async def spawn(self, rid, *args, persistent=False):
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=None)
        self.processes[rid] = proc
        await asyncio.sleep(0.2)
        if proc.returncode is not None:
            self.processes.pop(rid, None)
            raise Failure(502, f'audio process exited: {proc.returncode}')
        asyncio.create_task(self.watch(rid, proc, persistent))

    async def close(self, sid):
        session = self.sessions[sid]
        await self.stop(sid)
        self.arbiter.release(sid)
        session['state'] = 'closing'

    async def cleanup_session(self, sid):
        async with self.lock:
            session = self.sessions.get(sid)
            if session is None:
                return
            locations = list(session['locations'])
        failures = []
        for location in locations:
            try:
                async with self.client.delete(location) as response:
                    if response.status not in (200, 204):
                        raise Failure(502, f'MediaMTX DELETE failed: {response.status}')
                async with self.lock:
                    session['locations'].remove(location)
            except (Failure, aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
                failures.append(str(exc))
        async with self.lock:
            if not failures and session['state'] == 'closing':
                del self.sessions[sid]
        if failures:
            raise Failure(502, '; '.join(failures))

    async def create_session(self, request):
        data = await request.json()
        owner, mode = data['owner'], data['mode']
        if not isinstance(owner, str) or not owner.strip() or mode not in ('intercom', 'remote_announcement', 'video'):
            raise ValueError('invalid owner or mode')
        sid = uuid.uuid4().hex
        async with self.lock:
            if owner in self.closed_owners:
                raise Failure(409, 'owner is closed')
            if mode != 'video':
                await self.reserve(sid, mode)
            self.sessions[sid] = {'owner': owner, 'mode': mode, 'state': 'reserved', 'locations': [], 'kinds': []}
        return web.json_response({'session_id': sid, 'mode': mode, 'state': 'reserved'})

    def owned(self, sid, owner):
        if sid not in self.sessions:
            raise Failure(404, 'session not found')
        session = self.sessions[sid]
        if session['owner'] != owner:
            raise Failure(403, 'session owner mismatch')
        return session

    async def offer(self, request):
        data = await request.json()
        sid, kind, sdp = request.match_info['sid'], data['kind'], data['sdp']
        if not isinstance(sdp, str) or not sdp:
            raise ValueError('sdp is required')
        paths = {('intercom', 'publish'): 'platform_voice/whip', ('remote_announcement', 'publish'): 'platform_voice/whip', ('intercom', 'microphone'): 'robot_mic/whep', ('video', 'camera'): 'camera/whep'}
        async with self.lock:
            session = self.owned(sid, data['owner'])
            mode = session['mode']
            if (mode, kind) not in paths or session['state'] in ('failed', 'interrupted', 'closing'):
                raise Failure(409, 'offer is incompatible with session')
            if kind in session['kinds']:
                raise Failure(409, 'offer kind already established')
            session['kinds'].append(kind)
        async with self.media_lock:
            async with self.lock:
                if any(value['state'] == 'closing' and value['locations'] for value in self.sessions.values()):
                    session['kinds'].remove(kind)
                    raise Failure(409, 'session cleanup is pending')
                stale = [key for key, value in self.sessions.items() if value['state'] in ('interrupted', 'failed') and value['locations']]
            try:
                for old_sid in stale:
                    await self.cleanup_session(old_sid)
            except Failure:
                async with self.lock:
                    session['kinds'].remove(kind)
                raise
            async with self.lock:
                if session['state'] in ('failed', 'interrupted', 'closing'):
                    session['kinds'].remove(kind)
                    raise Failure(409, 'session was interrupted')
            try:
                async with self.client.post(urljoin(self.base, paths[mode, kind]), data=sdp, headers={'Content-Type': 'application/sdp'}) as response:
                    answer = await response.text()
                    if response.status != 201 or not response.headers.get('Location'):
                        raise Failure(502, f'MediaMTX offer failed: {response.status}')
                    location = urljoin(str(response.url), response.headers['Location'])
                async with self.lock:
                    session['locations'].append(location)
                    valid = session['state'] not in ('failed', 'interrupted', 'closing')
                    if valid and mode != 'video':
                        valid = bool(self.arbiter.owner and self.arbiter.owner.request_id == sid)
                if not valid:
                    await self.cleanup_session(sid)
                    raise Failure(409, 'session was interrupted')
                return web.json_response({'sdp': answer, 'type': 'answer'})
            except (aiohttp.ClientError, asyncio.TimeoutError, Failure, OSError):
                async with self.lock:
                    if kind in session['kinds'] and not session['locations']:
                        session['kinds'].remove(kind)
                raise

    async def activate(self, request):
        data = await request.json()
        sid = request.match_info['sid']
        async with self.lock:
            session = self.owned(sid, data['owner'])
            if (session['mode'] == 'video' or session['state'] != 'reserved'
                    or 'publish' not in session['kinds'] or not session['locations']):
                raise Failure(409, 'published audio is not ready for activation')
            try:
                await self.spawn(sid, 'gst-launch-1.0', '-q', 'rtspsrc', f'location={self.rtsp}/platform_voice', 'latency=100', '!', 'decodebin', '!', 'audioconvert', '!', 'audioresample', '!', 'pulsesink', f'device={self.sink}')
            except (OSError, Failure):
                session['state'] = 'failed'
                self.arbiter.release(sid)
                raise
            session['state'] = 'starting'
        return web.json_response({'state': 'starting'})

    async def delete_session(self, request):
        sid = request.match_info['sid']
        async with self.lock:
            self.owned(sid, request.query['owner'])
            await self.close(sid)
        async with self.media_lock:
            await self.cleanup_session(sid)
        return web.json_response({'closed': True})

    async def close_owner(self, request):
        async with self.lock:
            self.closed_owners.add(request.match_info['owner'])
            ids = [sid for sid, s in self.sessions.items() if s['owner'] == request.match_info['owner']]
            failures = []
            ready = []
            for sid in ids:
                try:
                    await self.close(sid)
                    ready.append(sid)
                except Failure as exc:
                    failures.append(f'{sid}: {exc}')
        async with self.media_lock:
            for sid in ready:
                try:
                    await self.cleanup_session(sid)
                except Failure as exc:
                    failures.append(f'{sid}: {exc}')
        if failures:
            raise Failure(502, '; '.join(failures))
        return web.json_response({'closed': True})

    async def status(self, request):
        owner = self.arbiter.owner
        return web.json_response({'available': not bool(self.blocked), 'capabilities': ['intercom', 'remote_announcement', 'video'], 'playback_state': next((s['state'] for s in self.sessions.values() if owner and s is self.sessions.get(owner.request_id)), 'reserved' if owner else 'idle'), 'owner': {'request_id': owner.request_id, 'source': owner.source.value} if owner else None, 'blocked': self.blocked, 'sos': self.sos, 'sessions': {sid: {k: v for k, v in s.items() if k not in ('locations', 'kinds')} for sid, s in self.sessions.items()}})

    async def speak(self, request):
        data = await request.json()
        source = data['source']
        if source not in ('patrol_tts', 'local_dialogue', 'sos'):
            raise ValueError('invalid source')
        if ('event' in data) == ('text' in data):
            raise ValueError('provide event or text')
        text = announcement_for(data['event']) if 'event' in data else data['text']
        if not isinstance(text, str) or not text.strip():
            raise ValueError('text is required')
        rid = uuid.uuid4().hex
        async with self.lock:
            if source == 'sos':
                if not self.sos or not self.arbiter.owner or self.arbiter.owner.request_id != 'sos-active':
                    raise Failure(409, 'SOS is not active')
                rid = 'sos-active'
                if rid in self.speech_busy:
                    raise Failure(409, 'SOS speech already active')
            else:
                await self.reserve(rid, source)
            self.speech_busy.add(rid)
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav') as wav:
                async with self.lock:
                    if not self.arbiter.owner or self.arbiter.owner.request_id != rid:
                        raise Failure(409, 'audio output was interrupted')
                    piper = await asyncio.create_subprocess_exec('piper', '--model', self.model, '--output_file', wav.name, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=None)
                    self.processes[rid] = piper
                await asyncio.wait_for(piper.communicate(text.encode('utf-8')), 30)
                async with self.lock:
                    if self.processes.get(rid) is piper:
                        self.processes.pop(rid)
                    if piper.returncode:
                        raise Failure(502, f'piper exited: {piper.returncode}')
                    if not self.arbiter.owner or self.arbiter.owner.request_id != rid:
                        raise Failure(409, 'audio output was interrupted')
                    proc = await asyncio.create_subprocess_exec('paplay', '--device', self.sink, wav.name, stdout=asyncio.subprocess.DEVNULL, stderr=None)
                    self.processes[rid] = proc
                await asyncio.wait_for(proc.wait(), 30)
                async with self.lock:
                    if self.processes.get(rid) is proc:
                        self.processes.pop(rid)
                    if proc.returncode:
                        raise Failure(502, f'paplay exited: {proc.returncode}')
        except asyncio.TimeoutError:
            raise Failure(504, 'speech process timed out')
        finally:
            async with self.lock:
                await self.stop(rid)
                self.speech_busy.discard(rid)
                if source != 'sos':
                    self.arbiter.release(rid)
        return web.json_response({'played': True})

    async def set_sos(self, request):
        data = await request.json()
        if not isinstance(data['active'], bool):
            raise ValueError('active must be boolean')
        async with self.lock:
            self.sos = data['active']
            if self.sos:
                if not self.arbiter.owner or self.arbiter.owner.source.value != 'sos':
                    await self.reserve('sos-active', 'sos')
            elif self.arbiter.owner and self.arbiter.owner.source.value == 'sos':
                await self.stop(self.arbiter.owner.request_id)
                self.arbiter.release(self.arbiter.owner.request_id)
        return web.json_response({'active': self.sos})

    async def recognize(self, request):
        data = await request.json()
        command = command_from_text(data['text']).value
        await self.command_queue.put(command)
        return web.json_response({'command': command})

    async def next_command(self, request):
        try:
            command = self.command_queue.get_nowait()
        except asyncio.QueueEmpty:
            return web.json_response({'command': None})
        return web.json_response({'command': command})


def create_app(token, base, media_token, sink, rtsp, model):
    @web.middleware
    async def auth(request, handler):
        if request.headers.get('Authorization') != 'Bearer ' + token:
            raise Failure(401, 'unauthorized')
        return await handler(request)
    service = AudioService(base, media_token, sink, rtsp, model)
    app = web.Application(middlewares=[errors, auth])
    app.on_startup.append(service.start)
    app.on_cleanup.append(service.shutdown)
    app.add_routes([web.post('/sessions', service.create_session), web.post('/sessions/{sid}/offer', service.offer), web.post('/sessions/{sid}/activate', service.activate), web.delete('/sessions/{sid}', service.delete_session), web.post('/owners/{owner}/close', service.close_owner), web.get('/status', service.status), web.post('/speak', service.speak), web.post('/sos', service.set_sos), web.post('/recognize', service.recognize), web.get('/commands/next', service.next_command)])
    return app


def main():
    env = os.environ
    web.run_app(create_app(env['IIR_INTERACTION_TOKEN'], env['IIR_MEDIAMTX_HTTP_BASE'], env['IIR_MEDIA_AUTH_SECRET'], env['IIR_AUDIO_SINK'], env['IIR_RTSP_BASE'], env['IIR_PIPER_MODEL']), host='127.0.0.1', port=8095, handler_cancellation=False)


if __name__ == '__main__':
    main()

"""Exercise delayed WP5 signaling over the real control WebSocket.
通过真实控制 WebSocket 测试延迟的 WP5 信令。
"""
import asyncio
import hashlib
import os
import socket
import sys
import time

import aiohttp
from aiohttp import web


async def main():
    calls = []
    started = asyncio.Event()
    intercom_count = 0
    async def create(request):
        nonlocal intercom_count
        data = await request.json()
        calls.append(('create', data['owner']))
        if data['mode'] == 'intercom':
            intercom_count += 1
            if intercom_count == 1:
                return web.json_response({'error': 'audio_busy'}, status=409)
            return web.json_response({'session_id': 'b' * 32})
        if data['mode'] == 'remote_announcement':
            return web.Response(text='invalid json', content_type='application/json')
        started.set()
        await asyncio.sleep(3)
        return web.json_response({'session_id': 'a' * 32})
    async def close(request):
        calls.append(('close', request.match_info['owner']))
        return web.json_response({})
    app = web.Application()
    app.router.add_post('/sessions', create)
    app.router.add_post('/owners/{owner}/close', close)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', 8095).start()
    test_password = 'worker-test-password'
    env = dict(os.environ, IIR_INTERACTION_TOKEN='worker-test-token',
               IIR_WEB_ORIGIN='https://robot.test',
               OPI_WEB_PASSWORD_SHA256=hashlib.sha256(test_password.encode()).hexdigest())
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    process = await asyncio.create_subprocess_exec(sys.argv[1], '--fake', '--port', str(port), env=env,
                                                    stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.sleep(.4)
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(f'http://127.0.0.1:{port}/ws', origin='https://robot.test') as ws:
                async def reply(kind):
                    async with asyncio.timeout(2):
                        while True:
                            result = await ws.receive_json()
                            if result.get('t') == kind:
                                return result
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'video', 'request_id': 'unauth'})
                assert not (await reply('interaction_reply'))['ok']
                await ws.send_json({'t': 'view', 'page': 'control'})
                await ws.send_json({'t': 'manual_login', 'username': 'admin', 'password': test_password})
                assert (await reply('manual_auth'))['ok']
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'video', 'request_id': 'delay'})
                await asyncio.wait_for(started.wait(), 1)
                before = time.monotonic()
                await ws.send_json({'t': 'ping', 'ts': 123})
                assert (await reply('pong'))['ts'] == 123
                assert time.monotonic() - before < .2
                before = time.monotonic()
                await ws.send_json({'t': 'motion_stop'})
                assert (await reply('patrol_status'))['ok']
                assert time.monotonic() - before < .2
                await ws.send_json({'t': 'view', 'page': 'map'})
                await asyncio.sleep(3.2)
                assert ('close', calls[0][1]) in calls
                await ws.send_json({'t': 'view', 'page': 'control'})
                started.clear()
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'video', 'request_id': 'second'})
                await asyncio.wait_for(started.wait(), 1)
                second_owner = [owner for action, owner in calls if action == 'create'][1]
                assert second_owner != calls[0][1]
                await ws.send_json({'t': 'manual_login', 'username': 'admin', 'password': 'wrong'})
                assert not (await reply('manual_auth'))['ok']
                await asyncio.sleep(3.2)
                assert ('close', second_owner) in calls
            async with client.ws_connect(f'http://127.0.0.1:{port}/ws', origin='https://robot.test') as ws:
                async def next_type(kind):
                    async with asyncio.timeout(3):
                        while True:
                            message = await ws.receive_json()
                            if message.get('t') == kind:
                                return message
                await ws.send_json({'t': 'view', 'page': 'control'})
                await ws.send_json({'t': 'manual_login', 'username': 'admin', 'password': test_password})
                assert (await next_type('manual_auth'))['ok']
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'intercom', 'request_id': 'busy'})
                assert not (await next_type('interaction_reply'))['ok']
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'intercom', 'request_id': 'after-busy'})
                assert (await next_type('interaction_reply'))['ok']
                await ws.send_json({'t': 'interaction', 'action': 'create', 'mode': 'remote_announcement', 'request_id': 'unknown'})
                result = await next_type('interaction_reply')
                assert not result['ok']
                async with asyncio.timeout(3):
                    while True:
                        msg = await ws.receive()
                        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            break
                assert ('close', calls[-1][1]) in calls
        print('PASS: delayed signaling, control responsiveness, authorization and generation cleanup')
    finally:
        process.terminate()
        await process.wait()
        await runner.cleanup()


asyncio.run(main())

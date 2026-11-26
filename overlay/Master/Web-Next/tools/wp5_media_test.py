"""Transport synthetic audio through the configured MediaMTX instance.
通过配置的 MediaMTX 实例传输合成音频。

Install aiohttp and aiortc in a test environment and pass a 1.11.3 binary.
在测试环境中安装 aiohttp 与 aiortc，并传入 1.11.3 版本二进制。
"""

import argparse
import asyncio
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from urllib.parse import urljoin

import aiohttp
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription


async def run(binary):
    root = Path(__file__).resolve().parents[3]
    source, receiver, denied = [RTCPeerConnection() for _ in range(3)]
    received = asyncio.Event()
    tasks = []

    async def consume(track):
        frame = await track.recv()
        assert frame.samples > 0
        received.set()

    @receiver.on('track')
    def on_track(track):
        tasks.append(asyncio.create_task(consume(track)))

    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'mediamtx.json'
        password = secrets.token_hex(16)
        env = os.environ | {
            'IIR_MEDIA_AUTH_SECRET': password,
            'IIR_CAMERA_UPSTREAM': 'rtsp://127.0.0.1:19999/camera',
            'IIR_MEDIAMTX_CONFIG': str(config),
        }
        assert subprocess.check_output([binary, '--version'], text=True).strip() == 'v1.11.3'
        subprocess.run(['python3', str(root / 'deploy/mediamtx/render.py')], env=env, check=True)
        process = await asyncio.create_subprocess_exec(binary, str(config),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(5):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError('MediaMTX exited before readiness')
                    try:
                        _, writer = await asyncio.open_connection('127.0.0.1', 8889)
                        writer.close()
                        await writer.wait_closed()
                        break
                    except ConnectionRefusedError:
                        await asyncio.sleep(.05)
            auth = aiohttp.BasicAuth('iir-interaction', password)
            base = 'http://127.0.0.1:8889'
            locations = []
            async with aiohttp.ClientSession(auth=auth) as trusted, aiohttp.ClientSession() as local:
                source.addTrack(AudioStreamTrack())
                await source.setLocalDescription(await source.createOffer())
                async with trusted.post(base + '/platform_voice/whip', data=source.localDescription.sdp,
                                        headers={'Content-Type': 'application/sdp'}) as response:
                    assert response.status == 201, await response.text()
                    answer = await response.text()
                    locations.append(urljoin(str(response.url), response.headers['Location']))
                await source.setRemoteDescription(RTCSessionDescription(answer, 'answer'))

                receiver.addTransceiver('audio', direction='recvonly')
                await receiver.setLocalDescription(await receiver.createOffer())
                async with local.post(base + '/platform_voice/whep', data=receiver.localDescription.sdp,
                                      headers={'Content-Type': 'application/sdp'}) as response:
                    assert response.status == 201, await response.text()
                    answer = await response.text()
                    locations.append(urljoin(str(response.url), response.headers['Location']))
                await receiver.setRemoteDescription(RTCSessionDescription(answer, 'answer'))
                await asyncio.wait_for(received.wait(), 5)

                denied.addTransceiver('video', direction='recvonly')
                await denied.setLocalDescription(await denied.createOffer())
                async with local.post(base + '/camera/whep', data=denied.localDescription.sdp,
                                      headers={'Content-Type': 'application/sdp'}) as response:
                    assert response.status == 400
                    assert 'authentication failed' in await response.text()
                for location in locations:
                    async with trusted.delete(location) as response:
                        assert response.status == 200
                print('PASS: WHIP/WHEP audio frames, camera authentication, media resource deletion')
        finally:
            for peer in (source, receiver, denied):
                await peer.close()
            for task in tasks:
                task.cancel()
            if process.returncode is None:
                process.terminate()
            await process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mediamtx_binary')
    asyncio.run(run(parser.parse_args().mediamtx_binary))

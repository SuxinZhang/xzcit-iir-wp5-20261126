#!/usr/bin/env python3
import json
import os
from pathlib import Path

password = os.environ['IIR_MEDIA_AUTH_SECRET']
upstream = os.environ['IIR_CAMERA_UPSTREAM']
if not password or (upstream and not upstream.startswith(('rtsp://', 'rtsps://'))):
    raise SystemExit('MediaMTX password is required; camera upstream must be empty or RTSP')
config = {
    'authMethod': 'internal',
    'authInternalUsers': [
        {'user': 'iir-interaction', 'pass': password, 'ips': ['127.0.0.1'],
         'permissions': [{'action': 'publish', 'path': 'platform_voice'},
                         {'action': 'read', 'path': 'robot_mic'},
                         {'action': 'read', 'path': 'camera'}]},
        {'user': 'any', 'ips': ['127.0.0.1'],
         'permissions': [{'action': 'publish', 'path': 'robot_mic'},
                         {'action': 'read', 'path': 'platform_voice'}]},
    ],
    'api': False, 'rtmp': False, 'hls': False, 'srt': False,
    'rtspAddress': '127.0.0.1:8554', 'rtspTransports': ['tcp'],
    'webrtcAddress': '127.0.0.1:8889', 'webrtcLocalUDPAddress': ':8189',
    'webrtcLocalTCPAddress': '',
    'paths': {'robot_mic': {}, 'platform_voice': {}},
}
if upstream:
    config['paths']['camera'] = {'source': upstream}
path = Path(os.environ['IIR_MEDIAMTX_CONFIG'])
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as output:
    json.dump(config, output, ensure_ascii=False, indent=2)
    output.write('\n')
os.chmod(path, 0o600)

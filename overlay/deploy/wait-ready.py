#!/usr/bin/env python3
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

target = sys.argv[1]
ports = {'rtsp': 8554, 'webrtc': 8889, 'web': 8088}
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    try:
        if target == 'audio':
            request = urllib.request.Request('http://127.0.0.1:8095/status', headers={
                'Authorization': 'Bearer ' + os.environ['IIR_INTERACTION_TOKEN']})
            with urllib.request.urlopen(request, timeout=0.5) as response:
                body = json.load(response)
            if not isinstance(body, dict) or not {'available', 'owner', 'blocked', 'sos', 'sessions'} <= body.keys():
                raise ValueError('invalid audio status response')
            if body['available'] is not True or body['blocked'] is not None:
                raise ValueError('audio service is unavailable or blocked')
        else:
            with socket.create_connection(('127.0.0.1', ports[target]), timeout=0.5):
                pass
        sys.exit(0)
    except (ConnectionError, TimeoutError, urllib.error.URLError):
        time.sleep(0.1)
raise SystemExit(f'{target} readiness timed out after 10 seconds')

"""Recognize local audio and forward wake-word commands.
识别本地音频并转发唤醒词后的指令。
"""
# The wake path merges a streaming keyword hit with ASR text and keeps a short
# follow-up window. 唤醒路径合并流式关键词命中与识别文本，并保留短暂后续窗口。
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from .voice import command_text
from .wake import WakeSession


def save_recording(directory, pcm):
    """Save an explicitly enabled diagnostic segment as private PCM WAV.
    将显式启用的诊断片段保存为私有 PCM WAV。
    """
    path = Path(directory) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex + '.wav')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
    return str(path)


# The VAD starts a segment at the frame it calls speech, which can be tens of
# milliseconds after the real onset.  A single "小巡" stops matching once about
# 50 ms of its onset is missing, so the keyword decoder gets the audio just
# before the segment start.  Only the keyword path receives this pre-roll:
# feeding it to the recognizer would transcribe the previous utterance again.
# VAD 以判定为语音的那一帧作为片段起点，起音较弱时会晚几十毫秒；单次“小巡”
# 在起音缺失约 50 毫秒后就不再命中，因此关键词解码额外补上片段起点之前的音频。
# 只有关键词路径使用该前导：若喂给识别器，上一句尾音会被重复识别。
PRE_ROLL_SECONDS = 0.3
# The VAD reports a segment only after min_silence of silence has followed it, so
# its start is already behind the read position when it arrives.  Keep enough
# history to reach that start; a longer utterance loses the pre-roll, which does
# no harm because its wake word is surrounded by plenty of context.
# VAD 要在片段结束后静音 min_silence 才报告，收到片段时起点已在读取位置之后，
# 因此要保留足够历史。更长的句子拿不到前导也无妨，其唤醒词前后上下文充足。
_HISTORY_SECONDS = 2.0


def speech_segments(reader, vad, pre_roll_seconds=PRE_ROLL_SECONDS):
    """Yield each complete speech segment plus the audio just before it.
    返回每个完整语音片段，并附带该片段起点之前的音频。
    """
    import numpy as np

    cap = int(pre_roll_seconds * 16000)
    history = int(_HISTORY_SECONDS * 16000)
    chunks = []
    chunks_start = 0
    read = 0
    last_end = 0
    while True:
        audio = reader.read(512 * 2)
        if len(audio) != 512 * 2:
            raise RuntimeError('parec audio stream ended')
        chunk = np.frombuffer(audio, dtype='<i2').astype(np.float32) / 32768.0
        vad.accept_waveform(chunk)
        chunks.append(chunk)
        read += len(chunk)
        while not vad.empty():
            front = vad.front
            samples = np.array(front.samples, dtype=np.float32, copy=True)
            start = getattr(front, 'start', None)
            vad.pop()
            joined = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
            # The lead is always exactly cap samples: the measured hit rate
            # depends on where the phrase falls inside the decoded clip, so the
            # lead must not vary with how much history happens to be buffered.
            # 前导恒为 cap 个采样：实测命中率取决于短语在解码片段内的位置，
            # 因此前导长度不能随缓冲历史多少而变化。
            pre_roll = np.zeros(cap, dtype=np.float32)
            if start is None:
                end = read
            else:
                begin = max(chunks_start, last_end, start - cap)
                if begin < start:
                    available = joined[begin - chunks_start:start - chunks_start]
                    pre_roll[cap - len(available):] = available
                end = start + len(samples)
            yield samples, pre_roll
            last_end = max(last_end, end)
        # Audio before the next segment's pre-roll window can never be used, so
        # drop it instead of letting the buffer grow through long silence.
        # 下一片段前导窗口之前的音频不会再被用到，及时丢弃，避免长时间静音时
        # 缓冲区持续增长。
        keep_from = max(last_end, read - history)
        while chunks and chunks_start + len(chunks[0]) <= keep_from:
            chunks_start += len(chunks[0])
            chunks.pop(0)


# The dispatcher only talks to two fixed local service paths, so a wake
# transcript can never choose an arbitrary destination.
# 派发器只访问两个固定的本机服务路径，识别文本无法指定任意目标。
_SERVICE_PATHS = ('/speak', '/recognize')


def dispatch_text(text, keyword, wake, token, session=None, event=None):
    """Send a wake reply to speech, or forward one canonical command.
    将唤醒回应发送到播报接口，或转发一条规范指令。
    """
    if event is None:
        event = (session or WakeSession(wake)).handle(text, keyword)
    if event.command is not None:
        path, payload = '/recognize', {'text': command_text(event.command)}
    elif event.reply:
        path, payload = '/speak', {'text': event.reply, 'source': 'local_dialogue'}
    else:
        return False
    if path not in _SERVICE_PATHS:
        return False
    req = urllib.request.Request('http://127.0.0.1:8095' + path,
                                 data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req) as response:
            response.read()
        return True
    except urllib.error.HTTPError as exc:
        print(json.dumps({'event': 'dispatch_error', 'path': path,
                          'code': exc.code, 'text': payload['text']},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(json.dumps({'event': 'dispatch_error', 'path': path,
                          'error': type(exc).__name__, 'text': payload['text']},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return False


def _deliver_reply(event, token):
    """Speak the wake reply without blocking audio capture.
    在不阻塞音频采集的情况下播报唤醒回应。
    """
    started = time.monotonic()
    delivered = dispatch_text('', '', '', token, event=event)
    print(json.dumps({'event': 'asr_dispatch_result', 'source': event.source,
                      'reply': event.reply, 'delivered': delivered,
                      'dispatch_ms': round((time.monotonic() - started) * 1000)},
                     ensure_ascii=False), flush=True)


def main():
    import numpy as np
    import sherpa_onnx
    from .keywords import create_spotter, detect_keyword

    env = os.environ
    spotter = create_spotter(env)
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=env['IIR_ASR_ENCODER'], decoder=env['IIR_ASR_DECODER'],
        joiner=env['IIR_ASR_JOINER'], tokens=env['IIR_ASR_TOKENS'],
        num_threads=2, sample_rate=16000, feature_dim=80)
    wake = env.get('IIR_WAKE_WORD', '').strip()
    if not wake:
        raise ValueError('IIR_WAKE_WORD must not be empty')
    window_seconds = float(env.get('IIR_WAKE_WINDOW_SECONDS') or 6.0)
    if not 0.0 <= window_seconds <= 30.0:
        raise ValueError('IIR_WAKE_WINDOW_SECONDS must be between 0 and 30')
    min_silence = float(env.get('IIR_ASR_MIN_SILENCE_SECONDS') or 0.4)
    if not 0.0 < min_silence < 10.0:
        raise ValueError('IIR_ASR_MIN_SILENCE_SECONDS must be between 0 and 10')
    source = env['IIR_ASR_SOURCE']
    if not re.fullmatch(r'[A-Za-z0-9_.:@-]+', source) or source.startswith('-'):
        raise ValueError('IIR_ASR_SOURCE contains unsupported characters')
    config = sherpa_onnx.VadModelConfig()
    config.sample_rate = 16000
    config.silero_vad.model = env['IIR_ASR_VAD_MODEL']
    config.silero_vad.min_silence_duration = min_silence
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    session = WakeSession(wake, window_seconds)
    print(json.dumps({'event': 'asr_config', 'wake': wake,
                      'window_seconds': window_seconds,
                      'min_silence_seconds': min_silence,
                      'asr_source': source,
                      'kws': spotter.config}, ensure_ascii=False), flush=True)
    process = subprocess.Popen(['parec', '--device', env['IIR_ASR_SOURCE'], '--format=s16le', '--rate=16000', '--channels=1'], stdout=subprocess.PIPE)
    try:
        for audio, pre_roll in speech_segments(process.stdout, vad):
            recording = None
            if env.get('IIR_ASR_RECORD_DIR'):
                recording = save_recording(env['IIR_ASR_RECORD_DIR'],
                                           (np.clip(audio, -1, 32767 / 32768) * 32768).astype('<i2').tobytes())
            keyword_started = time.monotonic()
            keyword = detect_keyword(spotter, np.concatenate([pre_roll, audio]))
            keyword_ms = round((time.monotonic() - keyword_started) * 1000)
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, audio)
            started = time.monotonic()
            recognizer.decode_stream(stream)
            raw_text = stream.result.text
            text = raw_text.replace(' ', '')
            event = session.handle(text, keyword)
            print(json.dumps({'event': 'asr_result', 'text': raw_text,
                              'time': datetime.now(timezone.utc).isoformat(),
                              'recording': recording,
                              'keyword': keyword, 'keyword_ms': keyword_ms,
                              'wake_source': event.source,
                              'woke': event.woke, 'double': event.doubled,
                              'command': event.command.value if event.command else None,
                              'reply': event.reply,
                              'audio_ms': round(len(audio) / 16),
                              'decode_ms': round((time.monotonic() - started) * 1000)},
                             ensure_ascii=False), flush=True)
            started = time.monotonic()
            delivered = None
            if event.command is not None:
                delivered = dispatch_text(text, keyword, wake,
                                          env['IIR_INTERACTION_TOKEN'], event=event)
            elif event.reply:
                threading.Thread(target=_deliver_reply,
                                 args=(event, env['IIR_INTERACTION_TOKEN']),
                                 daemon=True).start()
            if event.woke or event.command is not None:
                print(json.dumps({'event': 'asr_dispatch', 'text': text,
                                  'wake_source': event.source,
                                  'delivered': delivered,
                                  'reply': event.reply,
                                  'dispatch_ms': round((time.monotonic() - started) * 1000)},
                                 ensure_ascii=False), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


if __name__ == '__main__':
    main()

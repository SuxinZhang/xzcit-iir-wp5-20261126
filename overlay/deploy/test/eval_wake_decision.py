"""Measure the production wake decision, not just the keyword model.

The service wakes on either acoustic evidence or transcript text, so the recall
that matters is WakeSession.handle(transcript, keyword).  This replays every
saved segment through the deployed spotter, recognizer and session, and prints
the per-recording verdict plus the totals.  Run it before and after changing the
acceptance rules to see whether the change actually helps and whether it wakes
on the sixteen ordinary-conversation segments.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

from iir_interaction.keywords import create_spotter, detect_keyword
from iir_interaction.wake import WakeSession

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
LEAD = np.zeros(4800, dtype=np.float32)


def load(path):
    with wave.open(path, 'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),
                             dtype='<i2').astype(np.float32) / 32768.0


def env_of():
    env = {}
    with open('/home/orangepi/.config/iir/wp5.env') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def main():
    env = env_of()
    spotter = create_spotter(env)
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=env['IIR_ASR_ENCODER'], decoder=env['IIR_ASR_DECODER'],
        joiner=env['IIR_ASR_JOINER'], tokens=env['IIR_ASR_TOKENS'],
        num_threads=2, sample_rate=16000, feature_dim=80)
    session = WakeSession(env.get('IIR_WAKE_WORD') or '小巡', 6.0)
    woke_pos, woke_neg = [], []
    for path in sorted(glob.glob(os.path.join(REC, '*.wav'))):
        name = os.path.basename(path)[17:23]
        audio = load(path)
        keyword = detect_keyword(spotter, np.concatenate([LEAD, audio]))
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, audio)
        recognizer.decode_stream(stream)
        text = stream.result.text.replace(' ', '')
        event = session.handle(text, keyword)
        if event.woke:
            (woke_pos if name in POS else woke_neg).append(name)
        print('%s %s kws=%r text=%s -> woke=%s src=%s' % (
            name, 'P' if name in POS else '-', keyword, text,
            event.woke, event.source), flush=True)
    missed = sorted(POS - set(woke_pos))
    print('wake recall=%d/5 missed=%s falsewake=%d/16 %s' % (
        len(POS) - len(missed), missed, len(woke_neg), sorted(woke_neg)), flush=True)


if __name__ == '__main__':
    main()

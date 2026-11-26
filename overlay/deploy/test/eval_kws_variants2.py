"""Narrow the winning keyword variant and check the threshold interplay.

The first pass showed "x iǎo q ún" buys nothing, "x iǎo q iǎo" loses a hit, and
"x iǎo n éng" recovers 42949Z at 4/5 with no false wakes.  This run asks two
follow-ups: does a lower threshold recover the last miss, and can a doubled
"小巡小声" spelling recover 56761Z without touching the sixteen negatives.
"""
import glob
import os
import wave

import numpy as np

from iir_interaction.keywords import create_spotter, detect_keyword

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
LEAD = np.zeros(4800, dtype=np.float32)

NENG = 'x iǎo n éng @小巡'
CONFIGS = [
    ('base@.25', '', '0.25'),
    ('neng@.25', NENG, '0.25'),
    ('neng@.20', NENG, '0.20'),
    ('neng@.15', NENG, '0.15'),
    ('neng2@.25', NENG + '\nx iǎo n éng x iǎo n éng @小巡', '0.25'),
    ('neng+xunxsheng@.25', NENG + '\nx iǎo x ún x iǎo sh ēng @小巡', '0.25'),
]


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
    clips = []
    for path in sorted(glob.glob(os.path.join(REC, '*.wav'))):
        clips.append((os.path.basename(path)[17:23], load(path)))
    for label, extra, threshold in CONFIGS:
        env['IIR_KWS_EXTRA_KEYWORDS'] = extra
        env['IIR_KWS_THRESHOLD'] = threshold
        spotter = create_spotter(env)
        hits, false = [], []
        for name, audio in clips:
            keyword = detect_keyword(spotter, np.concatenate([LEAD, audio]))
            if not keyword:
                continue
            (hits if name in POS else false).append(name)
        missed = sorted(POS - set(hits))
        print('%-20s recall=%d/5 missed=%s false=%d/16 %s' % (
            label, len(POS) - len(missed), missed, len(false),
            sorted(false)), flush=True)


if __name__ == '__main__':
    main()

"""Run the deployed keyword code on the saved wake segments.

The live log recorded an empty keyword for all five wake attempts, yet the
offline harness hits three of them.  Either the log predates the current code or
the production path differs from the harness.  This imports the installed
create_spotter/detect_keyword and the service environment, so a difference
points at the code rather than the eval.
"""
import glob
import os
import wave

import numpy as np

from iir_interaction.keywords import create_spotter, detect_keyword

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}


def load(path):
    with wave.open(path, 'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),
                             dtype='<i2').astype(np.float32) / 32768.0


def main():
    env = {}
    with open('/home/orangepi/.config/iir/wp5.env') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    spotter = create_spotter(env)
    hits = []
    for path in sorted(glob.glob(os.path.join(REC, '*.wav'))):
        name = os.path.basename(path)[17:23]
        audio = load(path)
        lead = np.zeros(4800, dtype=np.float32)
        keyword = detect_keyword(spotter, np.concatenate([lead, audio]))
        if keyword:
            hits.append(name)
        print('%s %s %r' % (name, 'P' if name in POS else '-', keyword), flush=True)
    missed = sorted(POS - set(hits))
    false = sorted(set(hits) - POS)
    print('recall=%d/5 false=%d/16 missed=%s falsepos=%s' % (
        len(POS) - len(missed), len(false), missed, false), flush=True)


if __name__ == '__main__':
    main()

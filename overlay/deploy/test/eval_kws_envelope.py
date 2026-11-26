"""Show the energy envelope of the focus segments in 50 ms frames.

A wake attempt that the keyword model cannot see at any threshold is usually
one of two things: the phrase was cut off by the VAD boundary, or the segment
does not contain the phrase at all.  The envelope distinguishes them.
"""
import glob
import os
import wave

import numpy as np

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
FOCUS = ('91500Z', '56761Z', '42949Z', '20034Z', '75094Z')
FRAME = 800  # 50 ms at 16 kHz


def main():
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in FOCUS:
            continue
        with wave.open(path, 'rb') as wav:
            data = wav.readframes(wav.getnframes())
        samples = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
        usable = len(samples) // FRAME * FRAME
        frames = samples[:usable].reshape(-1, FRAME)
        rms = np.sqrt((frames ** 2).mean(axis=1))
        db = 20 * np.log10(np.maximum(rms, 1e-9))
        # One character per 50 ms: a space under -50 dB, digits for louder.
        bars = ''.join(' ' if value < -50 else
                       '.' if value < -40 else
                       '-' if value < -30 else
                       '=' if value < -20 else '#'
                       for value in db)
        print(f'{name} {len(samples) / 16000:5.2f}s |{bars}|', flush=True)


if __name__ == '__main__':
    main()

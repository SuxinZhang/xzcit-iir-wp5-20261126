"""Test whether extra homophone spellings recover the missed wake phrases.

The installed keyword file only spells "x iǎo x ún" (小巡).  The ASR, however,
hears 小群 / 小能 / 小巧 for the same audio, which means the keyword model is
asked to match a pronunciation the speaker did not use.  Every pinyin unit
needed for those variants exists in tokens.txt, so the file can express them.

This adds each variant through the spotter's inline extra-keyword channel and
reports recall on the five wake attempts plus false hits on the sixteen
ordinary-conversation segments.  Nothing is written to the board.
"""
import glob
import os
import wave

import numpy as np

from iir_interaction.keywords import create_spotter, detect_keyword

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
LEAD = np.zeros(4800, dtype=np.float32)

# label is what the wake logic receives, so keep it "小巡" for every variant.
VARIANTS = [
    ('base', ''),
    ('qun', 'x iǎo q ún @小巡'),
    ('neng', 'x iǎo n éng @小巡'),
    ('qiao', 'x iǎo q iǎo @小巡'),
    ('all', 'x iǎo q ún @小巡\nx iǎo n éng @小巡\nx iǎo q iǎo @小巡'),
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
    for label, extra in VARIANTS:
        env['IIR_KWS_EXTRA_KEYWORDS'] = extra
        spotter = create_spotter(env)
        hits, false = [], []
        for name, audio in clips:
            keyword = detect_keyword(spotter, np.concatenate([LEAD, audio]))
            if not keyword:
                continue
            if name in POS:
                hits.append(name)
            else:
                false.append(name)
        missed = sorted(POS - set(hits))
        print('%-6s recall=%d/5 missed=%s false=%d/16 %s' % (
            label, len(POS) - len(missed), missed, len(false),
            sorted(false)), flush=True)


if __name__ == '__main__':
    main()

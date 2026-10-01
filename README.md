# audiocrop

Terminal audio trimmer with waveform display. Set start/end markers, render to normalized MP3 via ffmpeg.

## Install

```bash
pip install -r requirements.txt
```

Requires `ffmpeg` on PATH.

## Usage

```bash
python audiocrop.py <audio_file>
```

## Controls

| Key | Action |
|-----|--------|
| `space` | Play / pause |
| `h` / `←` | Back 10s |
| `l` / `→` | Forward 10s |
| `H` / `Shift+←` | Back 1s |
| `L` / `Shift+→` | Forward 1s |
| `B` | Back 30s |
| `W` | Forward 30s |
| `s` | Set start marker |
| `e` | Set end marker |
| `g` | Jump to start marker |
| `G` | Jump to end marker |
| `0` | Jump to beginning |
| `$` | Jump to end |
| `Enter` | Render selection to MP3 |
| `q` / `Esc` | Quit |

## Output

Renders the selection between markers as a loudness-normalized MP3 (`-q:a 0`, loudnorm to -16 LUFS) in the same directory as the source file.

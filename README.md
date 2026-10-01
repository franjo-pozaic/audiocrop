# audiocrop

Terminal audio trimmer with waveform display. Set start/end markers, render to normalized MP3 via ffmpeg.

## Install

```bash
pip install -r requirements.txt
```

Requires `ffmpeg` on PATH. The file picker needs `fzf` on PATH (optional, only used when you run without a file argument).

## Usage

```bash
python audiocrop.py <audio_file>   # open a specific file
python audiocrop.py <directory>    # pick a file in <directory> via fzf
python audiocrop.py                # pick a file in the current directory via fzf
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
| `r` | Toggle loop (loops the selection if both markers are set) |
| `+` / `-` | Volume up / down |
| `Enter` | Render selection to MP3 |
| `Tab` | Load next file in directory |
| `Shift+Tab` | Load previous file in directory |
| `D` | Delete current file (with confirmation) |
| `q` / `Esc` | Quit |

## Output

Renders the selection between markers as a loudness-normalized MP3 (`-q:a 0`, loudnorm to -16 LUFS) in the same directory as the source file.

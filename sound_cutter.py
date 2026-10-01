#!/usr/bin/env python3
"""
sound-cutter: Terminal audio file trimmer with waveform display.

Usage: python sound_cutter.py [audio_file]
       (without args, opens fzf picker in current directory)

Controls (vim-inspired):
  Space       - play / pause
  l / Right   - forward 10s
  h / Left    - backward 10s
  L / S-Right - forward 1s
  H / S-Left  - backward 1s
  W           - forward 30s
  B           - backward 30s
  s           - set start marker
  e           - set end marker
  Enter       - render selection to normalized mp3
  0           - jump to start of file
  $           - jump to end of file
  g           - jump to start marker
  G           - jump to end marker
  Tab         - load next file in directory
  q / Esc     - quit
"""

import curses
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioPlayer:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.info = sf.info(filepath)
        self.samplerate = self.info.samplerate
        self.channels = self.info.channels
        self.duration = self.info.duration
        self.total_frames = self.info.frames

        # Load full file into memory for waveform + playback
        self.data, _ = sf.read(filepath, dtype="float32")
        if self.data.ndim == 1:
            self.data = self.data.reshape(-1, 1)

        # Playback state
        self.position = 0  # current frame
        self.playing = False
        self.stream = None
        self.volume = 1.0  # linear gain multiplier
        self.loop = False
        self.loop_start = 0
        self.loop_end = self.total_frames
        self._lock = threading.Lock()

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            start = self.position
            end = start + frames

            if self.loop:
                loop_start = self.loop_start
                loop_end = self.loop_end
                # Fill output handling loop wrap
                written = 0
                while written < frames:
                    remaining = frames - written
                    chunk_end = min(start + remaining, loop_end)
                    chunk_len = chunk_end - start
                    if chunk_len <= 0:
                        start = loop_start
                        continue
                    outdata[written:written + chunk_len] = self.data[start:chunk_end] * self.volume
                    written += chunk_len
                    start = chunk_end
                    if start >= loop_end:
                        start = loop_start
                self.position = start
            else:
                if end > self.total_frames:
                    end = self.total_frames
                    self.playing = False
                chunk = self.data[start:end] * self.volume
                if len(chunk) < frames:
                    outdata[: len(chunk)] = chunk
                    outdata[len(chunk) :] = 0
                else:
                    outdata[:] = chunk
                self.position = end

    def play(self):
        if self.position >= self.total_frames:
            self.position = 0
        self.playing = True
        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                callback=self._callback,
                blocksize=1024,
            )
            self.stream.start()

    def pause(self):
        self.playing = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float):
        with self._lock:
            frame = self.position + int(seconds * self.samplerate)
            self.position = max(0, min(frame, self.total_frames))
            self._needs_flush = True

    def seek_to(self, seconds: float):
        with self._lock:
            self.position = max(0, min(int(seconds * self.samplerate), self.total_frames))
            self._needs_flush = True

    def flush_if_needed(self):
        """Call once per frame after processing all keys."""
        if not getattr(self, '_needs_flush', False):
            return
        self._needs_flush = False
        if self.stream and self.playing:
            self.stream.abort()
            self.stream.close()
            self.stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                callback=self._callback,
                blocksize=1024,
            )
            self.stream.start()

    @property
    def current_time(self) -> float:
        return self.position / self.samplerate

    def get_waveform_peaks(self, num_bins: int) -> np.ndarray:
        """Downsample audio to num_bins peak values for display. Cached."""
        if hasattr(self, '_peaks_cache') and self._peaks_cache[0] == num_bins:
            return self._peaks_cache[1]

        mono = self.data.mean(axis=1) if self.data.ndim > 1 else self.data.flatten()
        # Use reshape trick for speed instead of Python loop
        usable = (len(mono) // num_bins) * num_bins
        if usable > 0:
            reshaped = np.abs(mono[:usable]).reshape(num_bins, -1)
            peaks = reshaped.max(axis=1)
        else:
            peaks = np.zeros(num_bins)

        self._peaks_cache = (num_bins, peaks)
        return peaks


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac",
    ".wma", ".aiff", ".opus", ".webm", ".mp4",
}


def pick_file_fzf(directory: str = ".") -> str | None:
    """Open fzf to pick an audio file from directory."""
    # Find audio files
    audio_files = sorted(
        p for p in Path(directory).rglob("*")
        if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")
    )
    if not audio_files:
        print("No audio files found in current directory.")
        return None

    input_list = "\n".join(str(p) for p in audio_files)
    try:
        result = subprocess.run(
            ["fzf", "--prompt=audio> "],
            input=input_list,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        print("fzf not found. Install it or pass a file path directly.")
    return None


def get_audio_files_in_dir(filepath: str) -> list[str]:
    """Get sorted list of audio files in the same directory (resolved paths)."""
    directory = Path(filepath).resolve().parent
    return sorted(
        str(p.resolve()) for p in directory.iterdir()
        if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")
    )


def next_file(filepath: str) -> str | None:
    """Get the next audio file in the directory, wrapping around."""
    files = get_audio_files_in_dir(filepath)
    if len(files) <= 1:
        return None
    current = str(Path(filepath).resolve())
    try:
        idx = files.index(current)
    except ValueError:
        return files[0]
    next_idx = (idx + 1) % len(files)
    return files[next_idx]


def prev_file(filepath: str) -> str | None:
    """Get the previous audio file in the directory, wrapping around."""
    files = get_audio_files_in_dir(filepath)
    if len(files) <= 1:
        return None
    current = str(Path(filepath).resolve())
    try:
        idx = files.index(current)
    except ValueError:
        return files[-1]
    prev_idx = (idx - 1) % len(files)
    return files[prev_idx]


def format_time(seconds: float) -> str:
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"


def render_selection(filepath: str, start: float, end: float) -> str:
    """Render the selection to a normalized mp3 via ffmpeg (two-pass loudnorm)."""
    import json as _json

    src = Path(filepath)
    stem = src.stem

    def _ts(secs):
        m, s = divmod(int(secs), 60)
        return f"{m:02d}m{s:02d}s"

    out_name = f"{stem}_{_ts(start)}-{_ts(end)}.mp3"
    out_path = src.parent / out_name

    duration = end - start

    # Pass 1: measure loudness
    measure_cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", str(src),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null",
        "/dev/null",
    ]
    result = subprocess.run(measure_cmd, capture_output=True, text=True)
    # loudnorm stats are printed to stderr
    stderr = result.stderr

    # Parse the JSON block from stderr
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1
    if json_start == -1 or json_end == 0:
        raise RuntimeError(f"Failed to parse loudnorm output:\n{stderr[-300:]}")

    stats = _json.loads(stderr[json_start:json_end])

    # Pass 2: apply simple linear gain to hit -16 LUFS (no compression)
    measured_i = float(stats['input_i'])
    gain_db = -16.0 - measured_i

    # Clamp so true peak doesn't exceed -1.5 dBTP
    measured_tp = float(stats['input_tp'])
    max_gain = -1.5 - measured_tp
    gain_db = min(gain_db, max_gain)

    loudnorm_filter = f"volume={gain_db:.2f}dB"

    encode_cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", str(src),
        "-af", loudnorm_filter,
        "-codec:a", "libmp3lame",
        "-q:a", "0",
        str(out_path),
    ]
    subprocess.run(encode_cmd, capture_output=True, check=True)
    return str(out_path)


def main(stdscr, filepath: str):
    curses.curs_set(0)
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.timeout(16)  # ~60fps refresh

    # Init color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # waveform
    curses.init_pair(2, curses.COLOR_CYAN, -1)    # playhead
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # markers
    curses.init_pair(4, curses.COLOR_RED, -1)     # selection
    curses.init_pair(5, curses.COLOR_WHITE, -1)   # status
    curses.init_pair(6, curses.COLOR_MAGENTA, -1) # help

    player = AudioPlayer(filepath)

    start_marker = None  # in seconds
    end_marker = None
    status_msg = ""
    status_time = 0

    # Waveform block characters
    blocks = "░▒▓█"

    def load_file(new_path: str):
        nonlocal player, filepath, start_marker, end_marker, status_msg, status_time
        player.pause()
        filepath = new_path
        player = AudioPlayer(filepath)
        start_marker = None
        end_marker = None
        status_msg = f"Loaded: {Path(filepath).name}"
        status_time = time.time()

    while True:
        # Drain all pending keys before redrawing
        keys = []
        try:
            key = stdscr.get_wch()
            keys.append(key)
            # Keep reading while there are buffered keys
            while True:
                try:
                    key = stdscr.get_wch()
                    keys.append(key)
                except curses.error:
                    break
        except curses.error:
            pass

        for key in keys:
            # Handle input
            if key == " ":
                player.toggle()
            elif key == "q" or key == "\x1b":
                player.pause()
                return
            elif key == "h" or key == curses.KEY_LEFT:
                player.seek(-10)
            elif key == "l" or key == curses.KEY_RIGHT:
                player.seek(10)
            elif key == "H":
                player.seek(-1)
            elif key == "L":
                player.seek(1)
            elif key == "W":
                player.seek(30)
            elif key == "B":
                player.seek(-30)
            elif key == "s":
                start_marker = player.current_time
                status_msg = f"Start marker: {format_time(start_marker)}"
                status_time = time.time()
                if player.loop and end_marker is not None and start_marker < end_marker:
                    player.loop_start = int(start_marker * player.samplerate)
                    player.loop_end = int(end_marker * player.samplerate)
            elif key == "e":
                end_marker = player.current_time
                status_msg = f"End marker: {format_time(end_marker)}"
                status_time = time.time()
                if player.loop and start_marker is not None and start_marker < end_marker:
                    player.loop_start = int(start_marker * player.samplerate)
                    player.loop_end = int(end_marker * player.samplerate)
            elif key == "0":
                player.seek_to(0)
            elif key == "$":
                player.seek_to(player.duration)
            elif key == "g":
                if start_marker is not None:
                    player.seek_to(start_marker)
            elif key == "G":
                if end_marker is not None:
                    player.seek_to(end_marker)
            elif key == "\n" or key == curses.KEY_ENTER:
                if start_marker is not None and end_marker is not None:
                    if start_marker < end_marker:
                        player.pause()
                        status_msg = "Rendering..."
                        status_time = time.time()
                        stdscr.clear()
                        stdscr.addstr(0, 0, "Rendering... please wait")
                        stdscr.refresh()
                        try:
                            out = render_selection(filepath, start_marker, end_marker)
                            status_msg = f"Saved: {out}"
                        except subprocess.CalledProcessError as ex:
                            status_msg = f"ffmpeg error: {ex.stderr.decode()[:80]}"
                        status_time = time.time()
                    else:
                        status_msg = "Error: start must be before end"
                        status_time = time.time()
                else:
                    status_msg = "Set both markers first (s/e)"
                    status_time = time.time()
            # Arrow key escape sequences for shift/cmd combos
            elif key == curses.KEY_SLEFT:
                player.seek(-1)
            elif key == curses.KEY_SRIGHT:
                player.seek(1)
            elif key == "+" or key == "=":
                player.volume = min(5.0, player.volume + 0.1)
                status_msg = f"Volume: {player.volume:.0%}"
                status_time = time.time()
            elif key == "-":
                player.volume = max(0.0, player.volume - 0.1)
                status_msg = f"Volume: {player.volume:.0%}"
                status_time = time.time()
            elif key == "r":
                player.loop = not player.loop
                if player.loop:
                    if start_marker is not None and end_marker is not None and start_marker < end_marker:
                        player.loop_start = int(start_marker * player.samplerate)
                        player.loop_end = int(end_marker * player.samplerate)
                    else:
                        player.loop_start = 0
                        player.loop_end = player.total_frames
                    status_msg = f"Loop ON ({format_time(player.loop_start / player.samplerate)} → {format_time(player.loop_end / player.samplerate)})"
                else:
                    status_msg = "Loop OFF"
                status_time = time.time()
            elif key == "D":
                # Confirm delete
                player.pause()
                try:
                    stdscr.addstr(height - 2, 1, f"Delete {Path(filepath).name}? (y/N) ", curses.color_pair(4) | curses.A_BOLD)
                except curses.error:
                    pass
                stdscr.refresh()
                stdscr.nodelay(False)
                try:
                    confirm = stdscr.get_wch()
                except curses.error:
                    confirm = None
                stdscr.nodelay(True)
                stdscr.timeout(16)
                if confirm == "y" or confirm == "Y":
                    deleted_path = filepath
                    nf = next_file(filepath)
                    Path(deleted_path).unlink()
                    status_msg = f"Deleted: {Path(deleted_path).name}"
                    status_time = time.time()
                    if nf and nf != deleted_path:
                        load_file(nf)
                    else:
                        return
                else:
                    status_msg = "Delete cancelled"
                    status_time = time.time()
            elif key == "\t":
                nf = next_file(filepath)
                if nf:
                    load_file(nf)
                else:
                    status_msg = "No other audio files in directory"
                    status_time = time.time()
            elif key == curses.KEY_BTAB:
                pf = prev_file(filepath)
                if pf:
                    load_file(pf)
                else:
                    status_msg = "No other audio files in directory"
                    status_time = time.time()

        # Flush audio buffer once after all keys processed
        player.flush_if_needed()

        # Draw
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # Header
        fname = Path(filepath).name
        mode = "▶" if player.playing else "⏸"
        loop_indicator = " 🔁" if player.loop else ""
        vol = f"{player.volume:.0%}"
        header = f" {mode} {format_time(player.current_time)} / {format_time(player.duration)}  vol:{vol}{loop_indicator}"
        stdscr.addstr(0, 0, header[:width-1], curses.A_BOLD)
        # Filename right-aligned
        if len(fname) + len(header) + 2 < width:
            try:
                stdscr.addstr(0, width - len(fname) - 1, fname, curses.A_DIM)
            except curses.error:
                pass

        # Timeline ruler
        ruler_y = 1
        ruler = ""
        num_marks = min(10, width // 12)
        for i in range(num_marks + 1):
            t = (i / num_marks) * player.duration
            label = format_time(t)
            pos = int((i / num_marks) * (width - len(label) - 2))
            ruler = ruler.ljust(pos) + label
        try:
            stdscr.addstr(ruler_y, 1, ruler[:width-2], curses.A_DIM)
        except curses.error:
            pass

        # Waveform area — mirrored (centered on midline)
        wave_top = 3
        wave_height = max(6, height - 9)
        wave_width = width - 2
        mid_row = wave_top + wave_height // 2

        if wave_width > 0:
            peaks = player.get_waveform_peaks(wave_width)
            max_peak = peaks.max() if peaks.max() > 0 else 1.0

            # Positions in columns
            progress = player.current_time / player.duration if player.duration > 0 else 0
            playhead_col = int(progress * (wave_width - 1))

            start_col = None
            end_col = None
            if start_marker is not None:
                start_col = int((start_marker / player.duration) * (wave_width - 1))
            if end_marker is not None:
                end_col = int((end_marker / player.duration) * (wave_width - 1))

            half = wave_height // 2

            for col in range(wave_width):
                peak_norm = peaks[col] / max_peak
                bar_half = int(peak_norm * half)

                in_selection = (
                    start_col is not None
                    and end_col is not None
                    and start_col <= col <= end_col
                )

                x = col + 1

                # Draw the midline dot
                if col == playhead_col:
                    mid_char = "┃"
                    mid_color = curses.color_pair(2) | curses.A_BOLD
                elif col == start_col:
                    mid_char = "["
                    mid_color = curses.color_pair(3) | curses.A_BOLD
                elif col == end_col:
                    mid_char = "]"
                    mid_color = curses.color_pair(3) | curses.A_BOLD
                elif in_selection:
                    mid_char = "─"
                    mid_color = curses.color_pair(4) | curses.A_DIM
                else:
                    mid_char = "·"
                    mid_color = curses.A_DIM

                try:
                    stdscr.addch(mid_row, x, mid_char, mid_color)
                except curses.error:
                    pass

                # Draw bars above and below midline
                for i in range(1, half + 1):
                    y_up = mid_row - i
                    y_down = mid_row + i

                    if i <= bar_half:
                        if col == playhead_col:
                            ch_up = "┃"
                            ch_down = "┃"
                            color = curses.color_pair(2) | curses.A_BOLD
                        elif col == start_col or col == end_col:
                            ch_up = "│"
                            ch_down = "│"
                            color = curses.color_pair(3) | curses.A_BOLD
                        else:
                            # Gradient: brighter near midline, dimmer at edges
                            intensity = 1.0 - (i / half) * 0.6
                            if intensity > 0.7:
                                ch_up = "█"
                                ch_down = "█"
                            elif intensity > 0.4:
                                ch_up = "▓"
                                ch_down = "▓"
                            else:
                                ch_up = "░"
                                ch_down = "░"

                            if in_selection:
                                color = curses.color_pair(4)
                            else:
                                color = curses.color_pair(1)
                    else:
                        if col == playhead_col:
                            ch_up = "│"
                            ch_down = "│"
                            color = curses.color_pair(2) | curses.A_DIM
                        elif col == start_col or col == end_col:
                            ch_up = "│"
                            ch_down = "│"
                            color = curses.color_pair(3) | curses.A_DIM
                        else:
                            ch_up = " "
                            ch_down = " "
                            color = 0

                    if y_up >= wave_top and y_up < height - 1:
                        try:
                            stdscr.addch(y_up, x, ch_up, color)
                        except curses.error:
                            pass
                    if y_down < wave_top + wave_height and y_down < height - 1:
                        try:
                            stdscr.addch(y_down, x, ch_down, color)
                        except curses.error:
                            pass

        # Progress bar
        prog_y = wave_top + wave_height + 1
        if prog_y < height - 3 and wave_width > 0:
            filled = int(progress * wave_width)
            bar = "━" * filled + "╸" + "─" * (wave_width - filled - 1)
            try:
                stdscr.addstr(prog_y, 1, bar[:wave_width], curses.color_pair(2))
            except curses.error:
                pass

        # Marker info line
        info_y = wave_top + wave_height + 2
        if info_y < height - 2:
            marker_info = ""
            if start_marker is not None:
                marker_info += f" S:{format_time(start_marker)}"
            if end_marker is not None:
                marker_info += f"  E:{format_time(end_marker)}"
            if start_marker is not None and end_marker is not None:
                sel_dur = end_marker - start_marker
                marker_info += f"  ═ {format_time(abs(sel_dur))}"
            if marker_info:
                try:
                    stdscr.addstr(info_y, 1, marker_info[:width-2], curses.color_pair(3))
                except curses.error:
                    pass

        # Status message (fades after 5s)
        if status_msg and (time.time() - status_time < 5):
            status_y = height - 2
            if status_y > 0:
                try:
                    stdscr.addstr(status_y, 1, status_msg[:width-2], curses.color_pair(5))
                except curses.error:
                    pass

        # Help line at bottom
        help_y = height - 1
        help_text = " space:play  h/l:±10s  H/L:±1s  W/B:±30s  +/-:vol  s/e:markers  r:loop  ⏎:render  D:delete  tab:next  q:quit"
        try:
            stdscr.addstr(help_y, 0, help_text[:width-1], curses.color_pair(6) | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

    # Stop playback on exit
    player.pause()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        target = Path(sys.argv[1])
        if target.is_dir():
            filepath = pick_file_fzf(str(target))
            if not filepath:
                sys.exit(1)
        elif target.exists():
            filepath = str(target.resolve())
        else:
            print(f"File not found: {target}")
            sys.exit(1)
    else:
        filepath = pick_file_fzf()
        if not filepath:
            sys.exit(1)

    curses.wrapper(main, filepath)

# talking-head-video-tools

Small command-line tools for finishing talking-head and screen-recording videos with ffmpeg. Each tool does one job, takes its input and output paths as arguments, and prints `--help`. The defaults are numbers that were tuned on real short-form videos; each one is a flag or a named constant at the top of its script, with a note on what it does.

Most of the tools work from word timestamps: a JSON file that says when each word of the voice track is spoken. With that file you can cut pauses without touching the words, stretch a screen recording to fit its narration, and caption a video one word at a time.

## Tools

| Tool | What it does |
| --- | --- |
| `tighten.py` | Shortens the pauses between words and speeds the speech up without changing its pitch. Writes new word timestamps that match. |
| `retime_to_voice.py` | Retimes a screen recording so each on-screen step lasts as long as its voiceover line. |
| `reel.py` | Adds a punch-in zoom on every jump cut and burns in captions that highlight the spoken word. |
| `whisper_words.py` | Converts a Whisper word-timestamp transcript to the `words.json` format used here. |
| `nocatchlight.py` | Removes catchlights (reflections of a light) from the eyes in a still. |
| `podcast_still.py` | Gives a talking-head photo a dark studio look by pushing the background down behind the subject. |
| `grade_looks.py` | Renders five colour grades of a talking-head photo for side-by-side comparison. |
| `icloud_album.py` | Downloads every original from a public iCloud shared album. |
| `presets/*.txt` | Two ffmpeg audio filter chains for a voice track. |

## Install

You need Python 3.9 or newer, and `ffmpeg` and `ffprobe` on your PATH. ffmpeg must be built with libx264 and libass (`reel.py` uses the `ass` filter); the usual distribution builds have both.

```sh
git clone https://github.com/direksethi/talking-head-video-tools.git
cd talking-head-video-tools
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

What each tool imports:

| Tool | Python packages | Other |
| --- | --- | --- |
| `tighten.py` | numpy, soundfile | ffmpeg, ffprobe |
| `retime_to_voice.py` | none | ffmpeg, ffprobe |
| `reel.py` | none | ffmpeg with libass, ffprobe, a caption font (Montserrat by default) |
| `whisper_words.py` | none | ffprobe, only with `--audio` |
| `nocatchlight.py` | numpy, opencv-python-headless | |
| `podcast_still.py`, `grade_looks.py` | numpy, Pillow, rembg | rembg is not needed when you pass `--mask` |
| `icloud_album.py` | none | network access |

rembg downloads its segmentation model (`birefnet-portrait` by default, several hundred megabytes) the first time it runs. If you only want the audio and video tools, install `numpy soundfile` and skip the rest.

Run the tools from the repository folder, or by full path. They import `common.py`, which sits next to them.

## Word timestamps

The tools read one JSON format:

```json
{
  "duration": 6.2,
  "words": [
    {"word": "Open", "start": 0.50, "end": 0.82},
    {"word": "the", "start": 0.86, "end": 0.98},
    {"word": "settings", "start": 1.02, "end": 1.55}
  ]
}
```

- `start` and `end` are seconds from the start of the audio.
- `word` keeps its punctuation (`page.`, `theme,`). The caption tool breaks lines on it and the cue matcher ignores it.
- `duration` is the length of the audio in seconds. It is optional: `tighten.py` falls back to the length of the audio file, `retime_to_voice.py` to the end of the last word.
- A bare list of words is accepted too, and so are the short keys `w`, `s`, `e`.

Any tool that gives per-word times can produce this file. With [openai-whisper](https://github.com/openai/whisper):

```sh
whisper voice.wav --model small --word_timestamps True --output_format json
python whisper_words.py voice.json words.json --audio voice.wav
```

`whisper_words.py` reads the `segments[].words[]` layout that openai-whisper writes (WhisperX uses the same layout). Text-to-speech services that return character or word timings can be converted the same way: group the characters into words and write the three fields.

`examples/` holds a small `words.json`, `cues.json` and `cuts.json` to copy from.

## Worked examples

### tighten.py

```sh
python tighten.py voice.wav words.json tight.wav tight-words.json
python tighten.py voice.wav words.json tight.wav tight-words.json --tempo 1.0 --max-gap 0.3
```

Prints the length before and after, for example `14.47s -> 9.77s (20 words)`. Use `tight-words.json`, not the original, with anything you do to `tight.wav` afterwards.

How it works: every pause between two words that is longer than `--max-gap` (0.18 s) is cut down to that length plus 0.04 s of air, so the consonant that ends the word is not clipped. Each cut ends in a 200-sample fade so it does not click. At most 0.12 s of silence is kept before the first word and 0.3 s after the last. The result then goes through ffmpeg's `atempo` filter at `--tempo` (1.12). `atempo` is a time stretch: it plays the audio faster and leaves the pitch where it was, so the voice does not go up. The word times are recomputed for both steps.

### retime_to_voice.py

```sh
python retime_to_voice.py screen.mp4 voice.wav words.json cues.json out.mp4
```

`cues.json` lists the steps in the order they are narrated:

```json
[
  {"at": 0,                         "in": 0.0,  "out": 2.0},
  {"cue": "open the settings",      "in": 2.0,  "out": 4.6},
  {"cue": "then choose your theme", "in": 5.0,  "out": 10.4},
  {"cue": "and you are done",       "in": 12.0, "out": 12.4, "zoom": true, "after": 4}
]
```

| Field | Meaning |
| --- | --- |
| `cue` | The phrase that starts the step in the voiceover. Matched word for word against `words.json`; case and `, . ! ?` are ignored. |
| `at` | A start time in seconds, in place of `cue`. Use `0` for the opening step. |
| `after` | Only match the phrase at or after this time, for a phrase that is said more than once. |
| `in`, `out` | The part of the screen recording to show, in seconds. |
| `zoom` | `true` adds a slow push-in. Use it when a short clip has to be held for a long line. |

How it works: each step starts 0.12 s (`--lead`) before its cue word, so the picture changes just ahead of the voice. A step runs until the next step starts, and its clip is sped up or slowed down by a constant factor to fill exactly that time. The tool prints the factor for every step (`x1.96` is about twice as fast, `x0.55` is slow motion) so you can spot a step that is stretched too far. Zoom steps push in by 10 percent over their length (`--zoom-amount`), computed on a 2x upscale so the motion is smooth. The recording's own audio is dropped. The voiceover is padded with 0.6 s of silence (`--tail`), loudness-normalised to -14 LUFS and encoded as AAC. The output is H.264 at 30 fps (`--fps`) in the recording's own size.

### reel.py

```sh
python reel.py cut.mp4 cuts.json words.json reel.mp4
python reel.py cut.mp4 cuts.json words.json reel.mp4 --highlight 00E5FF --max-words 2 --font "Inter"
```

`cut.mp4` is your video with the bad takes and pauses already removed. `cuts.json` lists the ranges you kept, in seconds on the original timeline, in order:

```json
[[0.40, 2.20], [3.00, 4.65], [4.95, 6.10]]
```

`words.json` is on the original (uncut) timeline too. The tool maps each word onto the cut timeline and drops words that fall in removed ranges. It also saves the captions next to the output as `reel.ass`.

How the zooms work: each kept range is cropped to its own zoom level and scaled back to full size. The levels cycle through `1.12, 1.0, 1.16, 1.0, 1.08, 1.0` (`--zooms`), so the framing changes at every cut and the jump reads as a deliberate change of shot. The crop is centred horizontally. Vertically it leaves 18 percent of the spare height above the crop (`--anchor-y`), which keeps a face in the upper part of the frame at about the same place when the zoom changes.

How the captions work: words are grouped into captions of up to three (`--max-words`), and a caption ends early at a word that ends in `. , ? !`. For each word the tool writes one subtitle event that shows the whole caption with that word in the highlight colour, from the moment the word starts until the next one does. ffmpeg burns them in with libass. The style is bold white with a black outline, sized for a vertical frame (68 px at 1280 px of height) and scaled to the height of your video.

### whisper_words.py

```sh
python whisper_words.py voice.json words.json --audio voice.wav
```

Without `--audio`, `duration` is set to the end of the last word.

### nocatchlight.py

```sh
python nocatchlight.py portrait.png fixed.png 512,300 598,302 --iris-radius 14
```

Each `x,y` is the rough centre of a pupil, in pixels from the top left. Read them off in any image viewer. Set `--iris-radius` to the radius of the iris in your image; the default of 12 suits a face that is a few hundred pixels wide.

How it works: the centre snaps to the darkest point within 6 px. For each distance from the centre the tool takes the 30th percentile of the colours on that ring, which is the iris colour without the reflection. Pixels inside the iris that are more than `--delta` (15) levels brighter than that profile are replaced by it, with a soft edge and a little of the original grain put back.

### podcast_still.py

```sh
python podcast_still.py frame.jpg still.jpg
python podcast_still.py frame.jpg still.jpg --mask frame-mask.png
```

Cuts the subject out with rembg, then blurs the background, removes most of its colour (`--bg-saturation 0.22`), darkens it (`--bg-brightness 0.42`) and cools it slightly. The subject is warmed slightly and a vignette goes over both. The mask is saved as `still-mask.png`. Pass your own greyscale mask with `--mask` (white is the subject) to skip the model.

### grade_looks.py

```sh
python grade_looks.py frame.jpg looks/
python grade_looks.py frame.jpg looks/ --mask frame-mask.png
```

Writes five JPEGs to the folder: `1-clean-tech`, `2-teal-orange`, `3-warm-creator`, `4-moody-podcast` and `5-dark-tech-rgb`. Each look lights the subject with a soft key, treats the blurred background separately, then applies its own contrast, saturation, tone curve, shadow and highlight tint, and vignette. The fifth adds a violet and blue glow behind the subject and a thin rim of it on the subject's edge. The values for each look are in the script, a few lines per look, and are meant to be edited. The mask is cached as `looks/mask.png` and reused on the next run.

### icloud_album.py

```sh
python icloud_album.py "<public shared album link>" album/
```

Takes a public shared album link from photos.icloud.com, or just the key at the end of it. It makes the same anonymous requests the album web page makes, lists every item, and downloads the original file of each photo and video. Files already in the folder are skipped, so you can run it again after an interruption.

### Audio presets

Two `-af` filter chains for a single voice track:

```sh
ffmpeg -i voice.wav -af "$(cat presets/voice-clean.txt)" -ar 48000 voice-final.wav
ffmpeg -i mic.wav   -af "$(cat presets/voice-raw-mic.txt)" -ar 48000 voice-final.wav
```

`voice-clean.txt` is for a voice that is already free of noise:

| Stage | Setting | Purpose |
| --- | --- | --- |
| `highpass` | 80 Hz | Removes rumble below the voice. |
| `equalizer` | 250 Hz, -3 dB | Takes out boxiness. |
| `equalizer` | 120 Hz, +2 dB | Adds body. |
| `equalizer` | 3.5 kHz, +2 dB | Adds presence, so words stay clear on phone speakers. |
| `deesser` | intensity 0.3 | Softens harsh "s" sounds. |
| `acompressor` | -20 dB threshold, 3:1, 8 ms attack, 120 ms release, +2 dB makeup | Evens out loud and quiet words. |
| `alimiter` | 0.89 | Catches peaks before normalisation. |
| `loudnorm` | -14 LUFS, -1.5 dB true peak, LRA 7 | Targets the loudness that the large video platforms normalise to. |

`voice-raw-mic.txt` is the same chain for a raw microphone recording. It adds two noise-reduction stages after the high-pass, `arnndn` (RNNoise, mixed in at 85 percent) and `afftdn` (noise floor -50 dB, 8 dB reduction), and uses slightly different EQ (120 Hz +1.5 dB, 3.5 kHz +2.5 dB) and de-esser (0.35) values. `arnndn` needs an RNNoise model file, which is not included: download one (for example from the `rnnoise-models` project), save it as `rnnoise-model.rnnn` in the folder you run ffmpeg from, or edit the path in the preset. To run without a model, delete the `arnndn=...` stage.

`loudnorm` runs in a single pass here, so the result is close to the target, not exact; on short or sparse clips it can land a couple of LU low. It also resamples internally, which is why the examples set `-ar 48000`.

## Limitations

- The tools do not transcribe or cut. You bring the word timestamps, the cue list and the kept ranges.
- `tighten.py` only removes silence between words. It does not look at the audio, so the result is only as good as the word times: a late `end` keeps some pause, an early one clips the word. It reads formats libsndfile supports (WAV, FLAC, OGG), not MP4 or M4A. The video is not touched; use it on a voice track before you build the picture.
- `retime_to_voice.py` changes speed by a constant factor per step and drops or repeats frames to do it; there is no frame blending. Very slow factors look like a slideshow, which is what `zoom` is for. Steps must be in narration order.
- `reel.py` expects the input video to be exactly the kept ranges joined together. It re-encodes the video and copies the audio. Zoomed ranges are upscaled, so start from a source with resolution to spare. Caption line breaks follow word count and punctuation only, and a long word group can run wider than the frame at large font sizes. If the caption font is not installed, libass picks a substitute without warning.
- `nocatchlight.py` does not find eyes. You give the centres and the iris radius. It works on the bright spot only and assumes the rest of the iris is roughly even in tone around each ring.
- `podcast_still.py` and `grade_looks.py` depend on the quality of the mask. The model is trained on portraits; the grades assume one subject, roughly centred, with the face in the upper half of the frame.
- `icloud_album.py` uses the web endpoints behind the public album page. They are not a documented API and can change. It only works for albums that are shared publicly.
- Tested on Linux with ffmpeg 8 and Python 3.13. Paths with unusual characters are handled for inputs and outputs, but this has not been tested on Windows.

## License

MIT. See [LICENSE](LICENSE).

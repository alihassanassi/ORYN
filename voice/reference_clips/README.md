# Voice Reference Clips

Place reference WAV files here for Chatterbox voice cloning.

## Requirements

- Format: WAV, 24 kHz sample rate
- Duration: 10–30 seconds (longer = better clone quality)
- Content: Single speaker, no background noise or music
- Style: Match the desired output style (calm/formal/tactical)

## Expected Files

| Filename                 | Description                                          |
|--------------------------|------------------------------------------------------|
| `jarvis_reference.wav`   | Calm, precise British male voice (classic JARVIS)    |
| `india_reference.wav`    | Warm, confident voice (India persona)                |
| `ct7567_reference.wav`   | Firm, tactical military voice (CT-7567 Rex persona)  |
| `fallback_reference.wav` | Neutral, clear voice (general fallback)              |

## Recording Tips

1. Record 15–20 seconds of clear, uninterrupted speech.
2. Use a quiet room — no fans, AC, or keyboard noise in the clip.
3. Speak in the style you want JARVIS to output (calm and measured works best).
4. Export as WAV at 24 kHz, 16-bit or 32-bit float.
5. Save directly into this directory with the filename above.

## If a File Is Missing

Chatterbox will silently fall back to its built-in default voice.
No error is raised. The clip is optional — cloning is enhancement only.

## Profile Mapping (voice/profiles.py)

| Profile name          | Reference file              |
|-----------------------|-----------------------------|
| `chatterbox_jarvis`   | `jarvis_reference.wav`      |
| `chatterbox_india`    | `india_reference.wav`       |
| `chatterbox_ct7567`   | `ct7567_reference.wav`      |
| `chatterbox_tactical` | `ct7567_reference.wav`      |
| `chatterbox_default`  | none (model default voice)  |

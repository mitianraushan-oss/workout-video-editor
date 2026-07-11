"""Auto-captions: transcribe a video's speech via OpenAI and burn the
subtitles into the video with ffmpeg. Triggered manually per task — this is
deliberately not part of the autonomous edit loop.

All ffmpeg invocations use argv lists (never a shell), matching the security
invariant of the rest of the app.

Note: transcription uses OpenAI's audio API ('whisper-1' supports
response_format='srt' directly). If it starts erroring, verify the model id
(override with OPENAI_TRANSCRIBE_MODEL) against OpenAI's current docs.
"""
import os
import subprocess

from openai import OpenAI

from analyzer.video_analyzer import get_video_info

DEFAULT_TRANSCRIBE_MODEL = 'whisper-1'

# ASS style: bold white text with black outline, bottom-centered — the
# standard readable-caption look.
CAPTION_STYLE = (
    'Fontsize=18,Bold=1,Outline=2,Shadow=1,MarginV=40,Alignment=2,'
    'PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&'
)


def _run_ffmpeg(args, timeout=600):
    """argv-only ffmpeg call; returns (ok, stderr_tail)."""
    result = subprocess.run(['ffmpeg', '-y'] + args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        return False, result.stderr[-500:]
    return True, None


def _filter_escape(path):
    """Escape a path for use inside an ffmpeg filter argument."""
    return path.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


def burn_subtitles(input_file, srt_path, output_file):
    """Burn an existing .srt file into a video. Returns (ok, error)."""
    # force_style must be quoted inside the filter graph — its commas would
    # otherwise be parsed as filter-option separators
    vf = f"subtitles={_filter_escape(srt_path)}:force_style='{CAPTION_STYLE}'"
    return _run_ffmpeg(['-i', input_file, '-vf', vf, '-c:a', 'copy', output_file])


TRANSLATE_MODEL_ENV = 'OPENAI_PLANNER_MODEL'
DEFAULT_TRANSLATE_MODEL = 'gpt-5.1'


def translate_srt(srt_text, target_language, client):
    """Translate the subtitle text of an SRT to target_language, preserving
    indices and timestamps. Returns (translated_srt, error)."""
    model = os.environ.get(TRANSLATE_MODEL_ENV, DEFAULT_TRANSLATE_MODEL)
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=16000,
        messages=[
            {
                'role': 'system',
                'content': (
                    'You translate SRT subtitle files. Reply with ONLY the complete '
                    'translated SRT — same entry numbers, same timestamps, byte-identical '
                    'timing lines; translate only the caption text lines to '
                    f'{target_language}. If a line is already in {target_language}, keep '
                    'it unchanged. No code fences, no commentary.'
                ),
            },
            {'role': 'user', 'content': srt_text},
        ],
    )
    translated = (response.choices[0].message.content or '').strip()
    # A valid SRT must still carry its timing lines — anything else means the
    # model replied with commentary instead of the file
    if '-->' not in translated:
        return None, 'Translation did not return a valid SRT file.'
    return translated, None


def generate_captions(input_file, output_file, task_id, processing_status, api_key,
                      language=None):
    """Extract audio -> transcribe -> (optionally translate) -> burn captions.
    `language`: None/'auto' keeps the spoken language; otherwise captions are
    translated to that language. Updates processing_status like
    run_ffmpeg_pipeline does, so the existing status/download flow works."""
    status = processing_status[task_id]
    try:
        status['status'] = 'processing'
        status['progress'] = 5
        status['current_step'] = 'Checking audio track'

        info = get_video_info(input_file)
        if not any(s.get('codec_type') == 'audio' for s in info.get('streams', [])):
            status['status'] = 'error'
            status['error'] = 'This video has no audio track — nothing to transcribe.'
            return

        work_dir = os.path.dirname(output_file) or '.'
        os.makedirs(work_dir, exist_ok=True)
        audio_path = os.path.join(work_dir, 'caption_audio.mp3')
        srt_path = os.path.join(work_dir, 'captions.srt')

        status['progress'] = 15
        status['current_step'] = 'Extracting audio'
        ok, err = _run_ffmpeg(['-i', input_file, '-vn', '-ac', '1', '-ar', '16000', audio_path])
        if not ok:
            status['status'] = 'error'
            status['error'] = f'Audio extraction failed: {err}'
            return

        # OpenAI's transcription endpoint caps uploads at 25MB
        if os.path.getsize(audio_path) > 25 * 1024 * 1024:
            status['status'] = 'error'
            status['error'] = 'Audio track is too large to transcribe (over 25MB after extraction).'
            return

        status['progress'] = 35
        status['current_step'] = 'Transcribing speech (OpenAI)'
        client = OpenAI(api_key=api_key, timeout=600)
        model = os.environ.get('OPENAI_TRANSCRIBE_MODEL', DEFAULT_TRANSCRIBE_MODEL)
        with open(audio_path, 'rb') as audio_file:
            srt_text = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format='srt',
            )
        # response_format='srt' returns the SRT body as a plain string
        srt_text = srt_text if isinstance(srt_text, str) else getattr(srt_text, 'text', '')

        if not srt_text.strip():
            status['status'] = 'error'
            status['error'] = 'Transcription returned no speech — is anyone talking in this video?'
            return

        if language and language.lower() != 'auto':
            status['progress'] = 55
            status['current_step'] = f'Translating captions to {language}'
            srt_text, err = translate_srt(srt_text, language, client)
            if err:
                status['status'] = 'error'
                status['error'] = err
                return

        with open(srt_path, 'w') as f:
            f.write(srt_text)

        status['progress'] = 70
        status['current_step'] = 'Burning captions into video'
        ok, err = burn_subtitles(input_file, srt_path, output_file)
        if not ok:
            status['status'] = 'error'
            status['error'] = f'Caption burn-in failed: {err}'
            return

        if not os.path.exists(output_file):
            status['status'] = 'error'
            status['error'] = 'Caption step finished but produced no output file.'
            return

        status['status'] = 'completed'
        status['progress'] = 100
        status['output_file'] = output_file

    except Exception as e:
        status['status'] = 'error'
        status['error'] = str(e)
    finally:
        for temp in ('caption_audio.mp3',):
            p = os.path.join(os.path.dirname(output_file) or '.', temp)
            if os.path.exists(p):
                os.remove(p)

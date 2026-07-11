"""Dispatch one cycle's proposed task to the right executor (ffmpeg or OpenAI
image edit) and return a uniform result dict."""
import time

from analyzer.ffmpeg_executor import run_ffmpeg_commands

from . import openai_image_editor


def execute_task(decision, input_file, output_file, deadline, openai_api_key=None):
    """decision: the dict returned by propose_next_task (task_type/ffmpeg_commands/
    image_edit_prompt). deadline: time.monotonic() timestamp for this cycle's
    remaining time budget. Returns {'success': bool, 'output_file': str|None, 'error': str|None}."""
    task_type = decision.get('task_type')

    if task_type == 'ffmpeg':
        commands = decision.get('ffmpeg_commands') or []
        if not commands:
            return {'success': False, 'output_file': None, 'error': 'No ffmpeg_commands provided'}
        timeout = max(1, deadline - time.monotonic())
        return run_ffmpeg_commands(commands, input_file, output_file, timeout_seconds=timeout)

    if task_type == 'openai_image_edit':
        if not openai_api_key:
            return {'success': False, 'output_file': None, 'error': 'OPENAI_API_KEY not configured'}
        prompt = decision.get('image_edit_prompt') or ''
        if not prompt:
            return {'success': False, 'output_file': None, 'error': 'No image_edit_prompt provided'}
        timeout = max(1, deadline - time.monotonic())
        ok, out, err = openai_image_editor.edit_image(
            input_file, output_file, prompt, openai_api_key, timeout_seconds=timeout
        )
        return {'success': ok, 'output_file': out, 'error': err}

    return {'success': False, 'output_file': None, 'error': f'Unknown task_type: {task_type!r}'}

"""Tests for the autonomous edit loop. Uses DummyPlannerClient throughout so no
OpenAI API key or network access is required; ffmpeg itself still runs for
real against tiny generated fixtures so verifier/executor behavior is genuine."""
import os
import subprocess

import cv2
import numpy as np
import pytest

from analyzer.ffmpeg_executor import run_ffmpeg_commands
from fable_loop import cost_monitor, verifier
from fable_loop.openai_planner import DummyPlannerClient
from fable_loop.example_tasks import EXAMPLE_TASKS
from fable_loop.orchestrator import LoopConfig, run_loop

MINIMAL_ANALYSIS = {
    'duration': 1.0,
    'fps': 25,
    'resolution': {'width': 64, 'height': 64},
    'brightness': 120,
    'has_audio': False,
    'motion_segments': [],
    'suggestions': [],
}


@pytest.fixture
def tiny_video(tmp_path):
    path = tmp_path / 'input.mp4'
    cmd = [
        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=1',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f'ffmpeg unavailable or failed to generate fixture: {result.stderr[-300:]}')
    return str(path)


# ---------------------------------------------------------------- verifier --

def test_verify_output_missing_file(tmp_path):
    ok, reason, info = verifier.verify_output(str(tmp_path / 'nope.mp4'), is_image=False)
    assert not ok
    assert 'missing' in reason.lower()


def test_verify_output_valid_video(tiny_video):
    ok, reason, info = verifier.verify_output(tiny_video, is_image=False)
    assert ok
    assert info['duration'] > 0


def test_verify_output_corrupted_video(tmp_path):
    bogus = tmp_path / 'bogus.mp4'
    bogus.write_bytes(b'not a real video file')
    ok, reason, info = verifier.verify_output(str(bogus), is_image=False)
    assert not ok


def test_verify_output_valid_image(tmp_path):
    path = tmp_path / 'img.png'
    cv2.imwrite(str(path), np.zeros((10, 10, 3), dtype=np.uint8))
    ok, reason, info = verifier.verify_output(str(path), is_image=True)
    assert ok


def test_verify_output_corrupted_image(tmp_path):
    path = tmp_path / 'bad.png'
    path.write_bytes(b'not an image')
    ok, reason, info = verifier.verify_output(str(path), is_image=True)
    assert not ok


# ---------------------------------------------------------- ffmpeg_executor --

def test_run_ffmpeg_commands_refuses_non_ffmpeg(tmp_path, tiny_video):
    commands = [{'name': 'evil', 'command': f'rm -rf {tmp_path}'}]
    result = run_ffmpeg_commands(commands, tiny_video, str(tmp_path / 'out.mp4'))
    assert result['success'] is False
    assert 'Refused' in result['error']


def test_run_ffmpeg_commands_success(tmp_path, tiny_video):
    out = tmp_path / 'out.mp4'
    commands = [{'name': 'brighten', 'command': 'ffmpeg -i "{INPUT}" -vf "eq=brightness=0.2" -c:a copy "{OUTPUT}"'}]
    result = run_ffmpeg_commands(commands, tiny_video, str(out))
    assert result['success'] is True
    assert out.exists()


def test_run_ffmpeg_commands_bad_flag_fails(tmp_path, tiny_video):
    out = tmp_path / 'out.mp4'
    commands = [{'name': 'bad', 'command': 'ffmpeg -i "{INPUT}" -bogus-flag "{OUTPUT}"'}]
    result = run_ffmpeg_commands(commands, tiny_video, str(out))
    assert result['success'] is False


def test_run_ffmpeg_commands_timeout(tmp_path, tiny_video, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd='ffmpeg', timeout=kwargs.get('timeout'))

    monkeypatch.setattr('analyzer.ffmpeg_executor.subprocess.run', fake_run)
    commands = [{'name': 'slow', 'command': 'ffmpeg -i "{INPUT}" "{OUTPUT}"'}]
    result = run_ffmpeg_commands(commands, tiny_video, str(tmp_path / 'out.mp4'), timeout_seconds=1)
    assert result['success'] is False
    assert 'time budget' in result['error']


# -------------------------------------------------------------- cost_monitor --

def test_compute_cost_known_model():
    usage = {'input_tokens': 1_000_000, 'output_tokens': 1_000_000, 'model': 'gpt-5.1'}
    assert cost_monitor.compute_cost(usage) == 11.25


def test_compute_cost_unknown_model_uses_default_pricing():
    usage = {'input_tokens': 800_000, 'output_tokens': 0, 'model': 'unknown-model'}
    assert cost_monitor.compute_cost(usage) == 1.0


# --------------------------------------------------------------- orchestrator --

def test_loop_reaches_done(tmp_path, tiny_video):
    # EXAMPLE_TASKS[2] = brighten (succeeds), EXAMPLE_TASKS[3] = done
    client = DummyPlannerClient(tasks=[EXAMPLE_TASKS[2], EXAMPLE_TASKS[3]])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t1', input_file=tiny_video, goal='brighten it',
        analysis=MINIMAL_ANALYSIS, is_image=False, config=LoopConfig(max_cycles=5), client=client,
    )
    assert state['status'] == 'done'
    assert state['cycle'] == 2
    assert os.path.exists(os.path.join(tmp_path, 'fable_memory.md'))
    assert os.path.exists(os.path.join(tmp_path, 'fable_state.json'))


def test_loop_stops_on_max_cycles(tmp_path, tiny_video):
    # Always proposes the same successful brighten task, never signals done.
    client = DummyPlannerClient(tasks=[EXAMPLE_TASKS[2]])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t2', input_file=tiny_video, goal='brighten forever',
        analysis=MINIMAL_ANALYSIS, is_image=False, config=LoopConfig(max_cycles=3), client=client,
    )
    assert state['status'] == 'stopped'
    assert state['stop_reason'] == 'max_cycles_reached'
    assert state['cycle'] == 3


def test_loop_flags_repeated_failing_task(tmp_path, tiny_video):
    bad_task = {
        'done': False,
        'summary': 'always broken',
        'task_type': 'ffmpeg',
        'ffmpeg_commands': [{'name': 'bad', 'command': 'ffmpeg -i "{INPUT}" -bogus-flag "{OUTPUT}"'}],
        'image_edit_prompt': '',
    }
    client = DummyPlannerClient(tasks=[bad_task])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t3', input_file=tiny_video, goal='do something impossible',
        analysis=MINIMAL_ANALYSIS, is_image=False,
        config=LoopConfig(max_cycles=10, max_repeat=3), client=client,
    )
    assert state['status'] == 'needs_intervention'
    assert state['stop_reason'] == 'repeated_task'
    assert state['cycle'] == 3


def test_loop_stops_on_budget_exhausted(tmp_path, tiny_video):
    class HighCostClient(DummyPlannerClient):
        def propose_next_task(self, **kwargs):
            decision, _ = super().propose_next_task(**kwargs)
            usage = {'input_tokens': 1_000_000, 'output_tokens': 1_000_000, 'model': 'gpt-5.1'}
            return decision, usage

    client = HighCostClient(tasks=[EXAMPLE_TASKS[2]])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t4', input_file=tiny_video, goal='brighten',
        analysis=MINIMAL_ANALYSIS, is_image=False,
        config=LoopConfig(max_cycles=10, budget_usd=0.001), client=client,
    )
    assert state['status'] == 'stopped'
    assert state['stop_reason'] == 'budget_exhausted'
    assert state['cycle'] == 1
    assert state['cumulative_cost_usd'] > 0.001


def test_loop_recovers_from_one_truncated_response(tmp_path, tiny_video):
    # Cycle 1 truncates (max_tokens hit mid-proposal), cycle 2 recovers with a
    # real proposal and succeeds — truncation should be retryable, not fatal.
    class OnceTruncatedClient(DummyPlannerClient):
        def __init__(self, tasks):
            super().__init__(tasks=tasks)
            self._first_call = True

        def propose_next_task(self, **kwargs):
            if self._first_call:
                self._first_call = False
                usage = {'input_tokens': 100, 'output_tokens': 8192, 'model': 'gpt-5.1'}
                return {'truncated': True, 'summary': 'ran out of tokens'}, usage
            return super().propose_next_task(**kwargs)

    client = OnceTruncatedClient(tasks=[EXAMPLE_TASKS[2], EXAMPLE_TASKS[3]])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t6', input_file=tiny_video, goal='brighten it',
        analysis=MINIMAL_ANALYSIS, is_image=False, config=LoopConfig(max_cycles=5), client=client,
    )
    assert state['status'] == 'done'
    assert state['cycle'] == 3  # truncated, then brighten, then done


def test_loop_flags_repeated_truncation(tmp_path, tiny_video):
    class AlwaysTruncatedClient(DummyPlannerClient):
        def propose_next_task(self, **kwargs):
            usage = {'input_tokens': 100, 'output_tokens': 8192, 'model': 'gpt-5.1'}
            return {'truncated': True, 'summary': 'ran out of tokens'}, usage

    client = AlwaysTruncatedClient(tasks=[])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t7', input_file=tiny_video, goal='brighten it',
        analysis=MINIMAL_ANALYSIS, is_image=False,
        config=LoopConfig(max_cycles=10, max_repeat=3), client=client,
    )
    assert state['status'] == 'needs_intervention'
    assert state['stop_reason'] == 'repeated_truncation'
    assert state['cycle'] == 3


def test_loop_stop_control_file_halts_next_cycle(tmp_path, tiny_video):
    # run_loop resets fable_control.json to stop_requested=False at startup
    # (a fresh loop shouldn't inherit a stale flag), so simulate the stop
    # request arriving *during* cycle 1 instead of pre-seeding the file.
    from fable_loop import memory as fable_memory

    control_path = os.path.join(tmp_path, 'fable_control.json')

    class StoppingClient(DummyPlannerClient):
        def propose_next_task(self, **kwargs):
            decision, usage = super().propose_next_task(**kwargs)
            if kwargs['cycle_num'] == 1:
                fable_memory.write_control(control_path, {'stop_requested': True})
            return decision, usage

    client = StoppingClient(tasks=[EXAMPLE_TASKS[2]])
    state = run_loop(
        task_dir=str(tmp_path), task_id='t5', input_file=tiny_video, goal='brighten',
        analysis=MINIMAL_ANALYSIS, is_image=False, config=LoopConfig(max_cycles=5), client=client,
    )
    assert state['status'] == 'stopped'
    assert state['stop_reason'] == 'user_requested'
    assert state['cycle'] == 1

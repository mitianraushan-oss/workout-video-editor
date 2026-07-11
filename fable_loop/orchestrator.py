"""Core autonomous edit loop: propose one bounded task -> execute -> verify ->
promote or roll back -> log to memory.md -> repeat until done, stopped, or an
edge case (timeout/repeat/budget) ends the run."""
import hashlib
import json
import os
import time

from . import cost_monitor, memory, task_executor, verifier
from .openai_planner import OpenAIPlannerClient


class LoopConfig:
    def __init__(self, max_cycles=20, cycle_timeout_seconds=1800, max_repeat=3, budget_usd=2.0):
        self.max_cycles = max_cycles
        self.cycle_timeout_seconds = cycle_timeout_seconds
        self.max_repeat = max_repeat
        self.budget_usd = budget_usd


def _ext(path):
    return os.path.splitext(path)[1] or '.mp4'


def _signature(decision):
    payload = {
        'task_type': decision.get('task_type'),
        'ffmpeg_commands': decision.get('ffmpeg_commands'),
        'image_edit_prompt': decision.get('image_edit_prompt'),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def run_loop(*, task_dir, task_id, input_file, goal, analysis, is_image,
             openai_api_key=None, config=None, client=None):
    """Runs cycles until done/stopped. Returns the final state dict. Writes
    fable_state.json, fable_memory.md, and reads fable_control.json (stop flag)
    from task_dir throughout — safe to poll from another thread/process."""
    config = config or LoopConfig()
    client = client or OpenAIPlannerClient(api_key=openai_api_key)

    os.makedirs(task_dir, exist_ok=True)
    state_path = os.path.join(task_dir, 'fable_state.json')
    memory_path = os.path.join(task_dir, 'fable_memory.md')
    control_path = os.path.join(task_dir, 'fable_control.json')

    state = {
        'goal': goal,
        'task_id': task_id,
        'cycle': 0,
        'current_input': input_file,
        'last_good_input': input_file,
        'status': 'running',
        'stop_reason': None,
        'cumulative_cost_usd': 0.0,
        'cumulative_input_tokens': 0,
        'cumulative_output_tokens': 0,
        'last_signature': None,
        'repeat_count': 0,
        'history_summaries': [],
    }
    memory.write_header(memory_path, goal, task_id)
    memory.save_state(state_path, state)
    memory.write_control(control_path, {'stop_requested': False})

    for cycle_num in range(1, config.max_cycles + 1):
        if memory.read_control(control_path).get('stop_requested'):
            state['status'] = 'stopped'
            state['stop_reason'] = 'user_requested'
            break

        if state['cumulative_cost_usd'] >= config.budget_usd:
            state['status'] = 'stopped'
            state['stop_reason'] = 'budget_exhausted'
            break

        state['cycle'] = cycle_num
        cycle_start = time.monotonic()

        try:
            decision, usage = client.propose_next_task(
                goal=goal,
                analysis=analysis,
                is_image=is_image,
                cycle_num=cycle_num,
                max_cycles=config.max_cycles,
                history=state['history_summaries'][-8:],
                budget_remaining_usd=config.budget_usd - state['cumulative_cost_usd'],
            )
        except Exception as e:
            memory.append_entry(memory_path, cycle_num, 'error', 'Planner call failed', error=str(e))
            state['status'] = 'error'
            state['stop_reason'] = f'planner_api_error: {e}'
            break

        cost = cost_monitor.compute_cost(usage)
        state['cumulative_cost_usd'] += cost
        state['cumulative_input_tokens'] += usage.get('input_tokens', 0)
        state['cumulative_output_tokens'] += usage.get('output_tokens', 0)

        if decision.get('refusal'):
            memory.append_entry(memory_path, cycle_num, 'refused', decision.get('summary', ''))
            state['status'] = 'error'
            state['stop_reason'] = 'model_refusal'
            break

        if decision.get('truncated'):
            # Not a decline — the model ran out of max_tokens mid-proposal. Treat it
            # like a failed cycle (retryable) rather than a hard stop, but still run
            # it through repeat detection so persistent truncation eventually flags
            # for intervention instead of looping forever.
            memory.append_entry(memory_path, cycle_num, 'truncated', decision.get('summary', ''))
            state['history_summaries'].append(f"Cycle {cycle_num}: TRUNCATED - {decision.get('summary')}")

            signature = 'truncated'
            if signature == state['last_signature']:
                state['repeat_count'] += 1
            else:
                state['repeat_count'] = 1
                state['last_signature'] = signature

            if state['repeat_count'] >= config.max_repeat:
                memory.append_entry(
                    memory_path, cycle_num, 'stuck', f'Response truncated {config.max_repeat}x in a row',
                )
                state['status'] = 'needs_intervention'
                state['stop_reason'] = 'repeated_truncation'
                break

            memory.save_state(state_path, state)
            continue

        if decision.get('done'):
            memory.append_entry(memory_path, cycle_num, 'done', decision.get('summary', 'Goal complete'))
            state['status'] = 'done'
            break

        signature = _signature(decision)
        if signature == state['last_signature']:
            state['repeat_count'] += 1
        else:
            state['repeat_count'] = 1
            state['last_signature'] = signature

        if state['repeat_count'] >= config.max_repeat:
            memory.append_entry(
                memory_path, cycle_num, 'stuck',
                f"Same task proposed {config.max_repeat}x in a row: {decision.get('summary')}",
            )
            state['status'] = 'needs_intervention'
            state['stop_reason'] = 'repeated_task'
            break

        deadline = cycle_start + config.cycle_timeout_seconds
        output_file = os.path.join(task_dir, f'cycle_{cycle_num}_output{_ext(input_file)}')

        result = task_executor.execute_task(
            decision, state['current_input'], output_file,
            deadline=deadline, openai_api_key=openai_api_key,
        )

        if not result['success']:
            memory.append_entry(
                memory_path, cycle_num, 'failed', decision.get('summary', ''), error=result.get('error')
            )
            state['history_summaries'].append(
                f"Cycle {cycle_num}: FAILED - {decision.get('summary')} ({result.get('error')})"
            )
            memory.save_state(state_path, state)
            continue

        ok, reason, info = verifier.verify_output(result['output_file'], is_image=is_image)

        if not ok:
            if result['output_file'] and os.path.exists(result['output_file']):
                os.remove(result['output_file'])
            memory.append_entry(
                memory_path, cycle_num, 'failed_verification', decision.get('summary', ''), error=reason
            )
            state['history_summaries'].append(
                f"Cycle {cycle_num}: VERIFICATION FAILED - {decision.get('summary')} ({reason})"
            )
            memory.save_state(state_path, state)
            continue

        # Success: promote this cycle's output to be the next cycle's input.
        state['last_good_input'] = result['output_file']
        state['current_input'] = result['output_file']
        state['repeat_count'] = 0
        state['last_signature'] = None
        memory.append_entry(memory_path, cycle_num, 'success', decision.get('summary', ''), info=info)
        state['history_summaries'].append(f"Cycle {cycle_num}: OK - {decision.get('summary')}")
        memory.save_state(state_path, state)
    else:
        state['status'] = 'stopped'
        state['stop_reason'] = 'max_cycles_reached'

    memory.save_state(state_path, state)
    memory.append_summary(memory_path, state)
    return state

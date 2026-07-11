"""Per-task loop memory: an append-only memory.md log, an atomically-written
state.json for loop control state, and a control.json for out-of-band stop requests."""
import json
import os
import time


def write_header(memory_path, goal, task_id):
    with open(memory_path, 'w') as f:
        f.write(f"# Fable Loop Memory — task {task_id}\n\n**Goal:** {goal}\n\n")


def append_entry(memory_path, cycle_num, outcome, summary, error=None, info=None):
    lines = [
        f"## Cycle {cycle_num} — {outcome}",
        f"- Summary: {summary}",
        f"- Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if error:
        lines.append(f"- Error: {error}")
    if info:
        lines.append(f"- Info: {json.dumps(info)}")
    lines.append('')
    with open(memory_path, 'a') as f:
        f.write('\n'.join(lines) + '\n')


def append_summary(memory_path, state):
    lines = [
        '---',
        '',
        f"## Loop finished — status: {state.get('status')}",
        f"- Stop reason: {state.get('stop_reason')}",
        f"- Cycles run: {state.get('cycle')}",
        f"- Total cost: ${state.get('cumulative_cost_usd', 0):.4f}",
        f"- Final output: {state.get('current_input')}",
        '',
    ]
    with open(memory_path, 'a') as f:
        f.write('\n'.join(lines) + '\n')


def save_state(state_path, state):
    tmp = state_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, state_path)


def load_state(state_path):
    if not os.path.exists(state_path):
        return {}
    with open(state_path) as f:
        return json.load(f)


def write_control(control_path, control):
    tmp = control_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(control, f)
    os.replace(tmp, control_path)


def read_control(control_path):
    if not os.path.exists(control_path):
        return {}
    try:
        with open(control_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

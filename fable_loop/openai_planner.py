"""Calls an OpenAI chat model once per cycle to decide the next bounded edit task.

The planner never edits media itself — it proposes one bounded ffmpeg edit (video)
or one GPT Image 2 edit (image) per cycle; task_executor.py performs it.

Note: this talks to OpenAI's API — if it starts erroring, verify the model id
(override with OPENAI_PLANNER_MODEL) and the structured-output request shape
against OpenAI's current docs.
"""
import json
import os

from openai import OpenAI

from .example_tasks import EXAMPLE_TASKS

DEFAULT_PLANNER_MODEL = 'gpt-5.1'

TASK_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'done': {
            'type': 'boolean',
            'description': (
                'True only when the stated goal has already been fully achieved '
                'by prior cycles and no further edits are needed.'
            ),
        },
        'summary': {
            'type': 'string',
            'description': "One sentence: this cycle's task, or why the goal is complete.",
        },
        'task_type': {
            'type': 'string',
            'enum': ['ffmpeg', 'openai_image_edit', 'none'],
            'description': "'none' only when done is true.",
        },
        'ffmpeg_commands': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'command': {'type': 'string'},
                },
                'required': ['name', 'command'],
                'additionalProperties': False,
            },
            'description': (
                'Ordered ffmpeg command templates using {INPUT} and {OUTPUT} '
                "placeholders. Empty unless task_type is 'ffmpeg'."
            ),
        },
        'image_edit_prompt': {
            'type': 'string',
            'description': (
                "Instruction for the image-edit model. Empty unless task_type "
                "is 'openai_image_edit'."
            ),
        },
    },
    'required': ['done', 'summary', 'task_type', 'ffmpeg_commands', 'image_edit_prompt'],
    'additionalProperties': False,
}


def _build_system_prompt(is_image):
    kind = 'still image' if is_image else 'video'
    return (
        f'You are the planner for an autonomous {kind} editing loop in a personal '
        'media-editing tool. You are called once per cycle. Each call, respond with '
        'JSON matching the given schema, containing exactly one of:\n'
        '- ONE bounded, independently-verifiable edit task for this cycle, or\n'
        "- done=true if the user's goal has already been fully achieved by prior cycles.\n\n"
        'Rules:\n'
        '- Propose exactly one logical edit per cycle (e.g. "add a 0.5s fade-in at the '
        'start", not "add all transitions, color-correct, and add music" in one go). '
        'Smaller, independently-verifiable steps are strongly preferred over large ones.\n'
        '- For task_type "ffmpeg": give the complete ffmpeg command(s) needed for this '
        'one edit. Each command must use {INPUT} and {OUTPUT} exactly once, as '
        "placeholders for the current file and this cycle's output file. Chain multiple "
        'ffmpeg steps only when a single ffmpeg invocation genuinely cannot express the edit.\n'
        '- task_type "openai_image_edit" is only usable when the file being edited is a '
        'still image (see is_image below).\n'
        '- If the cycle history below shows a task that failed or failed verification, do '
        'not propose the identical task again — adjust your approach based on the reported error.\n'
        '- Respect the remaining cycle and cost budgets given below; if either is nearly '
        "exhausted, wrap up with done=true rather than starting work you can't finish."
    )


def _condensed_analysis(analysis, is_image):
    if is_image:
        return {
            'resolution': analysis.get('resolution'),
            'brightness': analysis.get('brightness'),
            'suggestions': analysis.get('suggestions', [])[:5],
        }
    return {
        'duration_seconds': analysis.get('duration'),
        'fps': analysis.get('fps'),
        'resolution': analysis.get('resolution'),
        'brightness': analysis.get('brightness'),
        'has_audio': analysis.get('has_audio'),
        'motion_segments': analysis.get('motion_segments', [])[:8],
        'suggestions': analysis.get('suggestions', [])[:5],
    }


def _build_user_message(goal, analysis, is_image, cycle_num, max_cycles, history, budget_remaining_usd):
    payload = {
        'goal': goal,
        'is_image': is_image,
        'analysis': _condensed_analysis(analysis, is_image),
        'cycle_num': cycle_num,
        'cycles_remaining': max_cycles - cycle_num + 1,
        'budget_remaining_usd': round(budget_remaining_usd, 4),
        'cycle_history': history,
    }
    return json.dumps(payload, indent=2)


class OpenAIPlannerClient:
    """One structured-output chat completion per cycle."""

    def __init__(self, api_key, model=None):
        self._client = OpenAI(api_key=api_key)
        self._model = model or os.environ.get('OPENAI_PLANNER_MODEL', DEFAULT_PLANNER_MODEL)

    def propose_next_task(self, *, goal, analysis, is_image, cycle_num, max_cycles,
                           history, budget_remaining_usd):
        system = _build_system_prompt(is_image)
        user = _build_user_message(
            goal, analysis, is_image, cycle_num, max_cycles, history, budget_remaining_usd
        )

        response = self._client.chat.completions.create(
            model=self._model,
            max_completion_tokens=4096,
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'propose_edit_task',
                    'strict': True,
                    'schema': TASK_JSON_SCHEMA,
                },
            },
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        )

        usage = {
            'input_tokens': response.usage.prompt_tokens if response.usage else 0,
            'output_tokens': response.usage.completion_tokens if response.usage else 0,
            'model': response.model,
        }

        choice = response.choices[0]

        if getattr(choice.message, 'refusal', None):
            return {'refusal': True, 'summary': choice.message.refusal}, usage

        if choice.finish_reason == 'length':
            # Distinct from a refusal: the model was mid-proposal, not declining.
            # Surfaced separately so the orchestrator can retry instead of hard-stopping.
            return {
                'truncated': True,
                'summary': 'Response was truncated before completing the task proposal.',
            }, usage

        try:
            return json.loads(choice.message.content), usage
        except (TypeError, json.JSONDecodeError):
            return {'refusal': True, 'summary': 'No parseable task proposal returned.'}, usage


class DummyPlannerClient:
    """Deterministic stand-in for OpenAIPlannerClient — cycles through a fixed task
    list (EXAMPLE_TASKS by default). No network calls; for tests and dry-runs
    without an API key."""

    def __init__(self, tasks=None):
        self._tasks = tasks if tasks is not None else EXAMPLE_TASKS
        self._index = 0

    def propose_next_task(self, **kwargs):
        task = self._tasks[min(self._index, len(self._tasks) - 1)]
        self._index += 1
        usage = {'input_tokens': 0, 'output_tokens': 0, 'model': 'dummy'}
        return dict(task), usage

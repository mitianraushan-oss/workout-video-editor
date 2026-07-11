"""Example task proposals, in the exact shape Fable 5 returns from the
propose_edit_task tool. Used both as documentation of the task schema and as
deterministic fixtures for DummyFableClient (tests / dry-runs without an API key).
"""

EXAMPLE_TASKS = [
    {
        'done': False,
        'summary': 'Add a 0.5s fade-in at the start and fade-out at the end',
        'task_type': 'ffmpeg',
        'ffmpeg_commands': [
            {
                'name': 'Add fade in/out',
                'command': 'ffmpeg -i "{INPUT}" -vf "fade=t=in:st=0:d=0.5" -c:a copy "{OUTPUT}"',
            }
        ],
        'image_edit_prompt': '',
    },
    {
        'done': False,
        'summary': 'Trim the first 2 seconds of dead/quiet footage',
        'task_type': 'ffmpeg',
        'ffmpeg_commands': [
            {
                'name': 'Trim opening',
                'command': 'ffmpeg -i "{INPUT}" -ss 2 -c copy "{OUTPUT}"',
            }
        ],
        'image_edit_prompt': '',
    },
    {
        'done': False,
        'summary': 'Brighten a dark video by 20%',
        'task_type': 'ffmpeg',
        'ffmpeg_commands': [
            {
                'name': 'Brighten',
                'command': 'ffmpeg -i "{INPUT}" -vf "eq=brightness=0.2" -c:a copy "{OUTPUT}"',
            }
        ],
        'image_edit_prompt': '',
    },
    {
        'done': True,
        'summary': 'Goal fully achieved',
        'task_type': 'none',
        'ffmpeg_commands': [],
        'image_edit_prompt': '',
    },
]

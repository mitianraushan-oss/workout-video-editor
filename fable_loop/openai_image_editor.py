"""Edit a still image via OpenAI's GPT Image 2 edit endpoint.

Note: this talks to OpenAI's API, not Anthropic's — verify the model id and
`images.edit` response shape against OpenAI's current docs if it starts
returning unexpected errors, since their SDK surface isn't covered by any
skill available to this build.
"""
import base64
import urllib.request

from openai import OpenAI

IMAGE_EDIT_MODEL = 'gpt-image-2'


def edit_image(input_path, output_path, prompt, api_key, timeout_seconds=300):
    """Returns (success, output_file_or_None, error_or_None)."""
    try:
        client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        with open(input_path, 'rb') as image_file:
            result = client.images.edit(
                model=IMAGE_EDIT_MODEL,
                image=image_file,
                prompt=prompt,
            )
    except Exception as e:
        return False, None, f'OpenAI image edit request failed: {e}'

    data = result.data[0] if result.data else None
    if data is None:
        return False, None, 'OpenAI returned no image data'

    try:
        if getattr(data, 'b64_json', None):
            with open(output_path, 'wb') as out:
                out.write(base64.b64decode(data.b64_json))
        elif getattr(data, 'url', None):
            urllib.request.urlretrieve(data.url, output_path)
        else:
            return False, None, 'OpenAI response contained neither b64_json nor url'
    except Exception as e:
        return False, None, f'Failed to save OpenAI image output: {e}'

    return True, output_path, None

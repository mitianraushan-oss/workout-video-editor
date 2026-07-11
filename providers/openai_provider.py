"""Live OpenAI image integration for the provider layer.

Generation uses images.generate; editing reuses the existing
fable_loop.openai_image_editor.edit_image. Images are returned to the caller
as base64 (PNG) so the frontend can render them inline without any server-side
file storage.

The model id is configurable (OPENAI_IMAGE_MODEL) because OpenAI's image model
names change; resolve_image_model() can confirm what the key actually has.
"""
import base64
import logging
import os

from openai import OpenAI

log = logging.getLogger('providers.openai')

DEFAULT_IMAGE_MODEL = os.environ.get('OPENAI_IMAGE_MODEL', 'gpt-image-1')

# Sizes gpt-image-* accepts. 'auto' lets the model pick.
_ALLOWED_SIZES = {'auto', '1024x1024', '1024x1536', '1536x1024'}
_ALLOWED_QUALITY = {'auto', 'low', 'medium', 'high'}


def _client(api_key: str, timeout: int = 120) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=timeout)


def resolve_image_model(api_key: str) -> list[str]:
    """Return the image-capable model ids visible to this key (best-effort).
    Free call (models.list) — used to confirm the right id before generating."""
    try:
        models = _client(api_key).models.list()
        return sorted(m.id for m in models.data if 'image' in m.id.lower())
    except Exception as e:  # noqa: BLE001 - surfaced to caller for display
        log.warning('models.list failed: %s', e)
        return []


def generate_image(api_key: str, prompt: str, options: dict | None = None) -> dict:
    """Text -> image. Returns {'image_b64', 'model', 'size'}. Raises on failure."""
    options = options or {}
    model = options.get('model') or DEFAULT_IMAGE_MODEL
    size = options.get('size', '1024x1024')
    quality = options.get('quality', 'low')  # cheapest by default
    if size not in _ALLOWED_SIZES:
        size = '1024x1024'
    if quality not in _ALLOWED_QUALITY:
        quality = 'low'

    result = _client(api_key).images.generate(
        model=model, prompt=prompt, size=size, quality=quality, n=1,
    )
    data = result.data[0] if result.data else None
    if data is None:
        raise RuntimeError('OpenAI returned no image data')

    b64 = getattr(data, 'b64_json', None)
    if not b64:
        # Some models return a URL instead of inline b64; fetch and re-encode.
        url = getattr(data, 'url', None)
        if not url:
            raise RuntimeError('OpenAI response had neither b64_json nor url')
        import urllib.request
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - OpenAI host
            b64 = base64.b64encode(r.read()).decode()

    return {'image_b64': b64, 'model': model, 'size': size}


def edit_image_b64(api_key: str, input_path: str, prompt: str, options: dict | None = None) -> dict:
    """Image + prompt -> edited image (base64). Reuses the existing edit helper."""
    from fable_loop.openai_image_editor import edit_image
    import shutil
    import tempfile

    tmp_dir = tempfile.mkdtemp()
    try:
        out = os.path.join(tmp_dir, 'edited.png')
        ok, path, err = edit_image(input_path, out, prompt, api_key)
        if not ok:
            raise RuntimeError(err or 'OpenAI image edit failed')
        with open(path, 'rb') as f:
            return {'image_b64': base64.b64encode(f.read()).decode(), 'model': 'gpt-image (edit)'}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

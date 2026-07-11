"""Provider service: the single entry point the Flask app talks to.

Ties together the registry (static facts), credentials (keys present?), and
the usage tracker (budget left?). Selection prefers free tier, then lowest
cost, then configured priority.

DRY-RUN (default): controlled by env PROVIDER_DRY_RUN. Anything other than the
exact string 'false' keeps dry-run ON. In dry-run, generate_* makes NO network
call — it logs "Would call provider X ..." and returns a simulated result, but
STILL records usage so budget/limit logic can be exercised end-to-end.

To go live for a provider: implement its branch in _call_real() with the real
HTTP request (using requests / the provider SDK), then set PROVIDER_DRY_RUN=false
and provide the API key. Everything else — selection, budgeting, rate limiting,
error surfaces — already works.
"""
import logging
import os
import time
import uuid

from providers.registry import load_registry
from providers.credentials import CredentialManager
from providers.usage import UsageTracker, LimitExceeded

log = logging.getLogger('providers.service')


def _dry_run_enabled() -> bool:
    return os.environ.get('PROVIDER_DRY_RUN', 'true').strip().lower() != 'false'


def _require_user_key() -> bool:
    # Safe by default: a caller MUST supply their own key, so the server's env
    # keys can never be spent by a shared/public request. Set to 'false' only
    # for trusted single-tenant use where falling back to the app's key is OK.
    return os.environ.get('PROVIDER_REQUIRE_USER_KEY', 'true').strip().lower() != 'false'


class ProviderError(Exception):
    """Selection / availability error (no provider, not configured, over budget)."""


class ProviderService:
    def __init__(self, registry: dict | None = None, usage: UsageTracker | None = None):
        self.registry = registry if registry is not None else load_registry()
        self.credentials = CredentialManager(self.registry)
        # Inject `usage` in tests to point at an isolated state file.
        self.usage = usage if usage is not None else UsageTracker(self.registry)
        self.dry_run = _dry_run_enabled()
        self.require_user_key = _require_user_key()
        log.info('ProviderService ready (dry_run=%s, require_user_key=%s, providers=%d)',
                 self.dry_run, self.require_user_key, len(self.registry))

    # ---------- discovery ----------

    def _is_available(self, p) -> tuple[bool, str | None]:
        if not p.enabled:
            return False, 'disabled'
        if not self.credentials.has_credentials(p.id):
            return False, 'missing credentials'
        ok, reason = self.usage.can_spend(p.id, 1)
        if not ok:
            return False, reason
        return True, None

    def list_available(self) -> list[dict]:
        """Providers that are enabled, credentialed, and have budget remaining."""
        out = []
        for p in self.registry.values():
            ok, reason = self._is_available(p)
            if ok:
                d = p.to_public_dict()
                d['budget'] = self.usage.budget(p.id)
                out.append(d)
        out.sort(key=lambda d: d['priority'])
        return out

    def get_provider_for_task(self, task_type: str) -> str:
        """Pick the best available provider for a task type. Raises ProviderError.

        Order: prefer a free tier (daily/one-time/rate-limited) over paid-only,
        then lower cost_per_unit, then configured priority.
        """
        candidates = []
        for p in self.registry.values():
            if not p.supports(task_type):
                continue
            ok, _ = self._is_available(p)
            if not ok:
                continue
            is_paid_only = p.free_tier_type == 'paid-only'
            cost = p.cost_per_unit_usd if p.cost_per_unit_usd is not None else 0.0
            candidates.append((is_paid_only, cost, p.priority, p.id))

        if not candidates:
            raise ProviderError(f'no available provider for task {task_type!r}')
        candidates.sort()
        return candidates[0][3]

    # ---------- generation ----------

    def generate_image(self, provider_id, prompt, options=None, api_key=None):
        return self._generate('image', 'gen', provider_id, prompt, options or {}, api_key)

    def generate_video(self, provider_id, prompt, options=None, api_key=None):
        return self._generate('video', 'gen', provider_id, prompt, options or {}, api_key)

    def edit_image(self, provider_id, prompt, options=None, api_key=None):
        return self._generate('image', 'edit', provider_id, prompt, options or {}, api_key)

    def _generate(self, media, action, provider_id, prompt, options, api_key=None):
        p = self.registry.get(provider_id)
        if not p:
            raise ProviderError(f'unknown provider {provider_id!r}')
        task_type = f'{media}-{action}'
        if not p.supports(task_type):
            raise ProviderError(f'{p.name} does not support {task_type}')
        if not p.enabled:
            raise ProviderError(f'{p.name} is disabled')

        # BYO: a key supplied with the request wins; else fall back to env.
        byo = bool(api_key)
        # Safe-by-default: reject requests that would spend the server's own key,
        # so a shared/public page can never bill the app owner.
        if self.require_user_key and not byo:
            raise ProviderError(f'{p.name}: enter your own API key — this app uses your key, not the server\'s.')
        key = api_key or self.credentials.get_key(p.id)
        if not key:
            raise ProviderError(f'{p.name}: no API key provided')

        # The usage tracker guards an APP-OWNED shared free tier. With a
        # user-supplied (BYO) key the quota lives at the provider, so we only
        # enforce the shared gate when using the app's own env key.
        remaining = None
        if not byo:
            try:
                remaining = self.usage.record(p.id, 1)
            except LimitExceeded as e:
                raise ProviderError(str(e)) from e

        started = time.time()
        try:
            if self.dry_run:
                result = self._call_dry_run(task_type, p, prompt, options)
            else:
                result = self._call_real(task_type, p, prompt, options, key)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 - provider SDK/network errors
            # Convert raw SDK/network failures (bad key, content policy, provider
            # down) into a clean 4xx for the client. NOT logged here — the message
            # can contain a partial key, and it's returned only to the caller who
            # owns that key.
            raise ProviderError(f'{p.name} request failed: {e}') from e

        result.update({
            'provider': p.id,
            'provider_name': p.name,
            'dry_run': self.dry_run,
            'byo_key': byo,
            'processing_time': round(time.time() - started, 3),
            'remaining_budget': remaining,
        })
        return result

    def _call_dry_run(self, task_type: str, p, prompt: str, options: dict) -> dict:
        # NOTE: options must never contain secrets (api_key is stripped upstream).
        endpoint = p.endpoints.get(task_type, '(no endpoint configured)')
        log.info('DRY-RUN: would call provider %s %s%s | prompt=%r',
                 p.name, p.base_url, endpoint, prompt[:120])
        return {
            'status': 'ok',
            'url': f'dry-run://{p.id}/{task_type}/{uuid.uuid4().hex[:10]}',
            'tokens_used': 1,
            'note': f'DRY-RUN — no API called. Would POST {p.base_url}{endpoint}',
        }

    def _call_real(self, task_type: str, p, prompt: str, options: dict, key: str) -> dict:
        """Dispatch to the live per-provider integration. `key` is the resolved
        API key (BYO or env) and is NEVER logged."""
        if p.id == 'openai':
            from providers import openai_provider
            if task_type == 'image-gen':
                out = openai_provider.generate_image(key, prompt, options)
            elif task_type == 'image-edit':
                src = options.get('input_path')
                if not src:
                    raise ProviderError('image-edit requires an uploaded image')
                out = openai_provider.edit_image_b64(key, src, prompt, options)
            else:
                raise ProviderError(f'OpenAI does not support {task_type}')
            out['status'] = 'ok'
            return out

        # Other providers: plumbing is ready and the key flows through, but each
        # one's real HTTP call is unverified. Fill in per provider once you have
        # a key + confirmed API shape; until then fail loudly rather than guess.
        raise ProviderError(
            f'{p.name} live integration is not wired yet. The key was received, '
            f'but {p.id}\'s API call still needs to be implemented/verified in '
            f'providers/service._call_real().'
        )

    # ---------- status ----------

    def check_budget(self, provider_id: str) -> dict:
        if provider_id not in self.registry:
            raise ProviderError(f'unknown provider {provider_id!r}')
        return self.usage.budget(provider_id)

    def get_all_status(self) -> dict:
        providers = []
        for p in self.registry.values():
            ok, reason = self._is_available(p)
            entry = p.to_public_dict()
            entry.update({
                'has_credentials': self.credentials.has_credentials(p.id),
                'available': ok,
                'unavailable_reason': reason,
                'budget': self.usage.budget(p.id),
            })
            providers.append(entry)
        providers.sort(key=lambda d: d['priority'])
        return {'dry_run': self.dry_run, 'providers': providers}

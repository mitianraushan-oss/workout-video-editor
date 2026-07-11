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


class ProviderError(Exception):
    """Selection / availability error (no provider, not configured, over budget)."""


class ProviderService:
    def __init__(self, registry: dict | None = None, usage: UsageTracker | None = None):
        self.registry = registry if registry is not None else load_registry()
        self.credentials = CredentialManager(self.registry)
        # Inject `usage` in tests to point at an isolated state file.
        self.usage = usage if usage is not None else UsageTracker(self.registry)
        self.dry_run = _dry_run_enabled()
        log.info('ProviderService ready (dry_run=%s, providers=%d)', self.dry_run, len(self.registry))

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

    def generate_image(self, provider_id: str, prompt: str, options: dict | None = None) -> dict:
        return self._generate('image', provider_id, prompt, options or {})

    def generate_video(self, provider_id: str, prompt: str, options: dict | None = None) -> dict:
        return self._generate('video', provider_id, prompt, options or {})

    def _generate(self, media: str, provider_id: str, prompt: str, options: dict) -> dict:
        p = self.registry.get(provider_id)
        if not p:
            raise ProviderError(f'unknown provider {provider_id!r}')
        task_type = f'{media}-gen'
        if not p.supports(task_type):
            raise ProviderError(f'{p.name} does not support {task_type}')
        if not p.enabled:
            raise ProviderError(f'{p.name} is disabled')
        if not self.credentials.has_credentials(p.id):
            raise ProviderError(f'{p.name} has no credentials configured')

        # record() atomically enforces budget + rate limit before we spend.
        try:
            remaining = self.usage.record(p.id, 1)
        except LimitExceeded as e:
            raise ProviderError(str(e)) from e

        started = time.time()
        if self.dry_run:
            result = self._call_dry_run(media, p, prompt, options)
        else:
            result = self._call_real(media, p, prompt, options)

        result.update({
            'provider': p.id,
            'provider_name': p.name,
            'dry_run': self.dry_run,
            'processing_time': round(time.time() - started, 3),
            'remaining_budget': remaining,
        })
        return result

    def _call_dry_run(self, media: str, p, prompt: str, options: dict) -> dict:
        endpoint = p.endpoints.get(f'{media}-gen', '(no endpoint configured)')
        log.info('DRY-RUN: would call provider %s %s%s | prompt=%r | options=%s',
                 p.name, p.base_url, endpoint, prompt[:120], options)
        return {
            'status': 'ok',
            'url': f'dry-run://{p.id}/{media}/{uuid.uuid4().hex[:10]}',
            'tokens_used': 1,
            'note': f'DRY-RUN — no API called. Would POST {p.base_url}{endpoint}',
        }

    def _call_real(self, media: str, p, prompt: str, options: dict) -> dict:
        # Wire per-provider HTTP calls here, keyed on p.id, using
        # self.credentials.get_key(p.id) and p.base_url/p.endpoints.
        # Kept unimplemented on purpose so going live is a deliberate step.
        raise ProviderError(
            f'Live calls for {p.name} are not implemented yet. '
            f'Set PROVIDER_DRY_RUN=true, or implement _call_real() for {p.id}.'
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

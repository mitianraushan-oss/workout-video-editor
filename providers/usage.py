"""Usage tracker: enforce per-provider budgets and rate limits.

Handles the four free-tier shapes from providers.json:

  daily-credits      (Krea 100/day)   -> per-UTC-day counter, resets at midnight UTC
  one-time-credits   (Runway 125)     -> monotonic lifetime counter, never resets
  free-rate-limited  (Gemini, Grok)   -> per-minute AND per-day counters
  paid-only                           -> only rate_limit caps enforced (no free budget)

State is persisted to config/usage_state.json with atomic writes (os.replace),
matching fable_loop/memory.py. All mutations are guarded by a lock because
Flask serves requests on multiple threads.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger('providers.usage')

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'usage_state.json')


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _utc_minute() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')


def _next_utc_midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


class LimitExceeded(Exception):
    """Raised when a spend would push a provider over budget or rate limit."""
    def __init__(self, provider_id: str, reason: str, budget: dict):
        super().__init__(f"{provider_id}: {reason}")
        self.provider_id = provider_id
        self.reason = reason
        self.budget = budget


class UsageTracker:
    def __init__(self, registry: dict, state_path: str = STATE_PATH):
        self._registry = registry
        self._path = state_path
        self._lock = threading.RLock()
        self._state = self._load()

    # ---- persistence ----

    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                log.warning('usage_state.json unreadable; starting fresh')
        return {}

    def _save(self) -> None:
        tmp = self._path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp, self._path)

    def _entry(self, provider_id: str) -> dict:
        return self._state.setdefault(provider_id, {
            'day': _utc_day(),
            'day_count': 0,
            'minute': _utc_minute(),
            'minute_count': 0,
            'lifetime_count': 0,
        })

    def _roll_windows(self, e: dict) -> None:
        """Reset day/minute counters when their window has advanced."""
        today = _utc_day()
        if e.get('day') != today:
            e['day'] = today
            e['day_count'] = 0
        this_minute = _utc_minute()
        if e.get('minute') != this_minute:
            e['minute'] = this_minute
            e['minute_count'] = 0

    # ---- public API ----

    def budget(self, provider_id: str) -> dict:
        """Current budget snapshot: {current, limit, remaining, resets_at, kind}."""
        p = self._registry.get(provider_id)
        with self._lock:
            e = self._entry(provider_id)
            self._roll_windows(e)
            self._save()

            if not p:
                return {'current': 0, 'limit': None, 'remaining': None, 'resets_at': None, 'kind': 'unknown'}

            if p.free_tier_type == 'one-time-credits':
                limit = p.free_tier_limit if isinstance(p.free_tier_limit, int) else None
                used = e['lifetime_count']
                return {
                    'current': used, 'limit': limit,
                    'remaining': (max(limit - used, 0) if limit is not None else None),
                    'resets_at': None, 'kind': 'one-time-credits',
                }

            if p.free_tier_type == 'daily-credits':
                limit = p.free_tier_limit if isinstance(p.free_tier_limit, int) else None
                used = e['day_count']
                return {
                    'current': used, 'limit': limit,
                    'remaining': (max(limit - used, 0) if limit is not None else None),
                    'resets_at': _next_utc_midnight_iso(), 'kind': 'daily-credits',
                }

            if p.free_tier_type == 'free-rate-limited':
                rl = p.rate_limit or {}
                per_day = rl.get('per_day')
                return {
                    'current': e['day_count'],
                    'limit': per_day,
                    'remaining': (max(per_day - e['day_count'], 0) if per_day else None),
                    'resets_at': _next_utc_midnight_iso(),
                    'kind': 'free-rate-limited',
                    'per_minute': {'current': e['minute_count'], 'limit': rl.get('per_minute')},
                }

            # paid-only: only rate caps, no free budget concept
            rl = p.rate_limit or {}
            per_day = rl.get('per_day')
            return {
                'current': e['day_count'], 'limit': per_day,
                'remaining': (max(per_day - e['day_count'], 0) if per_day else None),
                'resets_at': _next_utc_midnight_iso() if per_day else None,
                'kind': 'paid-only',
            }

    def can_spend(self, provider_id: str, units: int = 1) -> tuple[bool, str | None]:
        """Check without mutating. Returns (ok, reason_if_not)."""
        p = self._registry.get(provider_id)
        if not p:
            return False, 'unknown provider'
        with self._lock:
            e = self._entry(provider_id)
            self._roll_windows(e)
            rl = p.rate_limit or {}

            per_min = rl.get('per_minute')
            if per_min is not None and e['minute_count'] + units > per_min:
                return False, f'rate limit: {per_min}/min reached'

            if p.free_tier_type == 'one-time-credits':
                limit = p.free_tier_limit
                if isinstance(limit, int) and e['lifetime_count'] + units > limit:
                    return False, f'one-time credits exhausted ({limit})'
            elif p.free_tier_type == 'daily-credits':
                limit = p.free_tier_limit
                if isinstance(limit, int) and e['day_count'] + units > limit:
                    return False, f'daily credits exhausted ({limit}/day)'
            else:  # free-rate-limited / paid-only day cap
                per_day = rl.get('per_day')
                if per_day is not None and e['day_count'] + units > per_day:
                    return False, f'daily cap reached ({per_day}/day)'
            return True, None

    def record(self, provider_id: str, units: int = 1) -> dict:
        """Atomically enforce + record a spend. Raises LimitExceeded if over."""
        with self._lock:
            ok, reason = self.can_spend(provider_id, units)
            if not ok:
                raise LimitExceeded(provider_id, reason, self.budget(provider_id))
            e = self._entry(provider_id)
            self._roll_windows(e)
            e['day_count'] += units
            e['minute_count'] += units
            e['lifetime_count'] += units
            self._save()
            return self.budget(provider_id)

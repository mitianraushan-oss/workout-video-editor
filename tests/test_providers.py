"""Tests for the multi-provider AI generation layer. No network access: the
service runs in dry-run, so generate_* never calls a real API. Each test uses
an isolated usage_state.json in a tmp dir so budget counters don't leak."""
import os

import pytest

from providers.registry import load_registry
from providers.usage import UsageTracker, LimitExceeded
from providers.service import ProviderService, ProviderError


@pytest.fixture
def service(tmp_path, monkeypatch):
    """Dry-run service with krea + gemini credentialed, isolated state file."""
    monkeypatch.setenv('PROVIDER_DRY_RUN', 'true')
    # These tests exercise the app-owned env-key + shared-budget path, so opt
    # out of the require-user-key guard (which is ON by default in production).
    monkeypatch.setenv('PROVIDER_REQUIRE_USER_KEY', 'false')
    monkeypatch.setenv('KREA_API_KEY', 'test-krea')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-gem')
    for missing in ('HIGGSFIELD_API_KEY', 'RUNWAY_API_KEY', 'GROK_API_KEY'):
        monkeypatch.delenv(missing, raising=False)
    registry = load_registry()
    usage = UsageTracker(registry, state_path=str(tmp_path / 'usage_state.json'))
    return ProviderService(registry=registry, usage=usage)


def test_only_credentialed_providers_available(service):
    ids = {p['id'] for p in service.list_available()}
    assert ids == {'krea', 'gemini'}


def test_selection_prefers_free_tier(service):
    # krea (daily-credits, priority 10) should win for image-gen
    assert service.get_provider_for_task('image-gen') == 'krea'


def test_dry_run_generate_records_usage(service):
    r = service.generate_image('krea', 'a poster')
    assert r['dry_run'] is True
    assert r['url'].startswith('dry-run://krea/')
    assert r['remaining_budget']['remaining'] == 99  # 100 daily - 1


def test_daily_credits_exhaust(service):
    reg = service.registry
    reg['krea'].free_tier_limit = 2  # shrink for a fast test
    service.generate_image('krea', 'a')
    service.generate_image('krea', 'b')
    with pytest.raises(ProviderError, match='daily credits exhausted'):
        service.generate_image('krea', 'c')


def test_per_minute_rate_limit(service):
    # gemini: 10/min. 11th call in the same minute is blocked.
    for i in range(10):
        service.generate_image('gemini', f'img {i}')
    with pytest.raises(ProviderError, match='rate limit'):
        service.generate_image('gemini', 'overflow')


def test_missing_credentials_blocks_generation(service):
    with pytest.raises(ProviderError, match='no API key'):
        service.generate_video('runway', 'x')


def test_byo_key_bypasses_shared_budget_gate(service):
    # Shrink krea's shared free tier to 0. The env-key path is now blocked...
    service.registry['krea'].free_tier_limit = 0
    with pytest.raises(ProviderError, match='exhausted'):
        service.generate_image('krea', 'x')
    # ...but a user-supplied (BYO) key bypasses the shared gate (dry-run ok).
    r = service.generate_image('krea', 'x', api_key='user-supplied-key')
    assert r['byo_key'] is True and r['status'] == 'ok'


def test_unsupported_task_rejected(service):
    with pytest.raises(ProviderError, match='does not support'):
        service.generate_video('gemini', 'x')  # gemini is image-only


def test_live_mode_refuses_until_implemented(tmp_path, monkeypatch):
    monkeypatch.setenv('PROVIDER_DRY_RUN', 'false')
    monkeypatch.setenv('KREA_API_KEY', 'test-krea')
    registry = load_registry()
    usage = UsageTracker(registry, state_path=str(tmp_path / 's.json'))
    svc = ProviderService(registry=registry, usage=usage)
    # Supply a user key so we get past the require-user-key guard and reach the
    # unwired-provider path that this test is actually about.
    with pytest.raises(ProviderError, match='not wired yet'):
        svc.generate_image('krea', 'x', api_key='user-key')


def test_require_user_key_guard_on_by_default(tmp_path, monkeypatch):
    # Default (no PROVIDER_REQUIRE_USER_KEY set) must reject a keyless request
    # even though the server HAS an env key — so a shared page can't spend it.
    monkeypatch.setenv('PROVIDER_DRY_RUN', 'true')
    monkeypatch.delenv('PROVIDER_REQUIRE_USER_KEY', raising=False)
    monkeypatch.setenv('KREA_API_KEY', 'server-owned-key')
    registry = load_registry()
    usage = UsageTracker(registry, state_path=str(tmp_path / 's.json'))
    svc = ProviderService(registry=registry, usage=usage)
    assert svc.require_user_key is True
    with pytest.raises(ProviderError, match='enter your own API key'):
        svc.generate_image('krea', 'x')                      # keyless -> blocked
    r = svc.generate_image('krea', 'x', api_key='friend-key')  # own key -> allowed
    assert r['byo_key'] is True


def test_budget_snapshot_shape(service):
    b = service.check_budget('runway')
    assert b['kind'] == 'one-time-credits'
    assert b['limit'] == 125 and b['remaining'] == 125 and b['resets_at'] is None

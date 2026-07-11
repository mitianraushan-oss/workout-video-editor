"""Multi-provider AI image/video generation layer.

Public surface used by the Flask app (see providers/routes.py):

    from providers.service import ProviderService
    service = ProviderService()               # loads config/providers.json
    service.list_available()                  # configured + within budget
    service.get_provider_for_task('image-gen')
    service.generate_image(provider, prompt, options)
    service.generate_video(provider, prompt, options)
    service.check_budget(provider)
    service.get_all_status()

Everything runs in DRY-RUN by default (PROVIDER_DRY_RUN != 'false'): no real
network calls are made — the service logs "Would call provider X" and returns
a simulated result. See providers/service.py for how to wire real HTTP calls.
"""

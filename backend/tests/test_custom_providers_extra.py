from types import SimpleNamespace

from backend.apps.agents.providers import registry


def test_custom_provider_slugify():
    name = "My Corp! Inc."
    slug = registry._custom_provider_slug_for_lookup(name)
    assert slug == "my-corp-inc"


def test_find_custom_provider_for_value_matches_slug():
    settings = SimpleNamespace(
        custom_providers=[
            SimpleNamespace(name="MyCorp", base_url="https://api.mycorp.test", api_key="sk-test"),
        ]
    )

    cp = registry._find_custom_provider_for_value(settings, "custom/mycorp/some-model")
    assert cp is not None
    assert getattr(cp, "name", None) == "MyCorp"

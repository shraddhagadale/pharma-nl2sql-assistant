from app.config import Settings


def test_blank_model_api_key_is_treated_as_unconfigured() -> None:
    settings = Settings(openai_api_key="")

    assert settings.openai_api_key is None

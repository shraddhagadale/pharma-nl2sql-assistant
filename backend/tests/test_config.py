from app.config import Settings


def test_blank_model_api_key_is_treated_as_unconfigured() -> None:
    settings = Settings(openai_api_key="")

    assert settings.openai_api_key is None


def test_model_defaults_to_sol_with_medium_reasoning() -> None:
    settings = Settings(openai_api_key="")

    assert settings.openai_model == "gpt-5.6-sol"
    assert settings.openai_reasoning_effort == "medium"

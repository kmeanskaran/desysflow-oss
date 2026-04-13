from services.llm import is_llm_limit_error


def test_detects_rate_limit_errors() -> None:
    exc = RuntimeError("Error code: 429 - Rate limit reached for requests")
    assert is_llm_limit_error(exc)


def test_detects_context_length_errors() -> None:
    exc = ValueError("This model's maximum context length is 128000 tokens.")
    assert is_llm_limit_error(exc)


def test_ignores_non_limit_errors() -> None:
    exc = RuntimeError("Connection refused to localhost:11434")
    assert not is_llm_limit_error(exc)

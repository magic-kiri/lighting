import pytest
from app.utils.llm_client import llm_text_query, llm_vision_query


def test_llm_text_query_returns_string():
    """Basic smoke test — send a trivial prompt, get a response."""
    response = llm_text_query(
        system="You are a helpful assistant. Respond with only the word 'OK'.",
        prompt="Say OK."
    )
    assert isinstance(response, str)
    assert len(response) > 0


def test_llm_vision_query_returns_string():
    """Smoke test with a tiny white PNG image."""
    import base64
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
        "Nl7BcQAAAABJRU5ErkJggg=="
    )
    response = llm_vision_query(
        system="Describe the image in one word.",
        prompt="What is this?",
        image_bytes=tiny_png,
        image_media_type="image/png"
    )
    assert isinstance(response, str)
    assert len(response) > 0

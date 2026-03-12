import base64
from app.config import (
    LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY,
    ANTHROPIC_MODEL, OPENAI_MODEL, GOOGLE_MODEL,
)


def llm_text_query(system: str, prompt: str) -> str:
    """Send a text-only query to the configured LLM provider."""
    if LLM_PROVIDER == "anthropic":
        return _anthropic_text(system, prompt)
    elif LLM_PROVIDER == "openai":
        return _openai_text(system, prompt)
    elif LLM_PROVIDER == "google":
        return _google_text(system, prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def llm_vision_query(system: str, prompt: str, image_bytes: bytes, image_media_type: str = "image/png") -> str:
    """Send a vision query (text + image) to the configured LLM provider."""
    if LLM_PROVIDER == "anthropic":
        return _anthropic_vision(system, prompt, image_bytes, image_media_type)
    elif LLM_PROVIDER == "openai":
        return _openai_vision(system, prompt, image_bytes, image_media_type)
    elif LLM_PROVIDER == "google":
        return _google_vision(system, prompt, image_bytes, image_media_type)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _anthropic_text(system: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _anthropic_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return msg.content[0].text


def _openai_text(system: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content


def _openai_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]},
        ],
    )
    return resp.choices[0].message.content


def _google_text(system: str, prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GOOGLE_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text


def _google_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GOOGLE_MODEL, system_instruction=system)
    image_part = {"mime_type": image_media_type, "data": image_bytes}
    resp = model.generate_content([image_part, prompt])
    return resp.text

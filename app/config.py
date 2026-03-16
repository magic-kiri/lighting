import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "") or os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
GOOGLE_PRO_MODEL = os.getenv("GOOGLE_PRO_MODEL", "gemini-2.5-pro")
RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "2"))
SCHEDULE_TEXT_THRESHOLD = int(os.getenv("SCHEDULE_TEXT_THRESHOLD", "1500"))
PDFPLUMBER_PAGE_TIMEOUT = int(os.getenv("PDFPLUMBER_PAGE_TIMEOUT", "60"))

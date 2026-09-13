# LearneAI — Gen-Z Language Learning Bot 🧠🔥

A modular, async Telegram language-learning bot (a Gen-Z, social spin on Duolingo):
adaptive placement quizzes, Leitner spaced repetition, voice messaging (STT/TTS),
dynamic API management via an admin panel, and the core **"Las o Lus" Roleplay Chat**.

## Tech Stack
- **aiogram 3.x** (strictly async, FSMContext)
- **SQLAlchemy 2.x async** + SQLite (PostgreSQL-ready via `DATABASE_URL`)
- **Groq (Llama-3/Mixtral)** or **Gemini** free tiers for LLM
- **Whisper** (Groq Audio / Hugging Face) for STT
- **edge-tts** for TTS
- **deep-translator / LibreTranslate** for translation
- JSON-based i18n, loaded per user language

## Project Structure
```
LearneAI/
├── main.py                  # Entry point: bot, dispatcher, router registration
├── requirements.txt
├── .env.example             # Copy to .env and fill in
├── handlers/
│   ├── __init__.py
│   ├── onboarding.py        # /start, language selection, level assessment quiz
│   ├── learning.py          # Daily goal, word presentation, Leitner reviews
│   ├── roleplay.py          # "Las o Lus" chat + voice notes
│   ├── dashboard.py         # Progress / mind-map / streak menu
│   └── admin.py             # Admin panel: live API management
├── database/
│   ├── __init__.py
│   ├── engine.py            # Async engine & session factory
│   ├── models.py            # Users, Vocabulary, LeitnerBox, ChatHistory, MindMap
│   └── crud.py              # All DB operations (async)
├── services/
│   ├── __init__.py
│   ├── llm_manager.py       # Dynamic provider switching, prompts, STT/TTS glue
│   ├── translation.py       # Google / LibreTranslate wrapper
│   └── scheduler.py         # Daily review & streak reminder jobs
├── keyboards/
│   ├── __init__.py
│   ├── inline.py            # Glass-style inline keyboards
│   └── menus.py             # Main menu / dashboard keyboards
├── utils/
│   ├── __init__.py
│   ├── config.py            # Typed settings from .env (pydantic-settings)
│   ├── i18n.py              # Dynamic text loader (locales/*.json)
│   └── leitner.py           # Spaced repetition intervals (Box 1→7)
├── locales/
│   └── (en.json, fa.json, es.json, ...)
└── learneai.db              # SQLite DB (created at runtime)
```

## Setup
```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # then edit values
python main.py
```

## Build Steps (delivered incrementally)
1. ✅ Structure, `requirements.txt`, `.env.example`
2. `database/models.py` + `database/crud.py`
3. `services/llm_manager.py` (dynamic API switching, prompts, STT/TTS)
4. `main.py` + `handlers/onboarding.py`
5. `handlers/learning.py` + `handlers/roleplay.py`

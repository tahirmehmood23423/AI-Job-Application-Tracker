---
title: Resume Parser API
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---
# Resume Parser API

> **Module 1 of the AI Job Application Tracker** — extracts structured data from resume PDFs and DOCX files using a hybrid approach: deterministic parsing for reliable fields + LLM extraction for messy free-form sections.

A production-grade FastAPI service that takes a resume file and returns clean, structured JSON with name, contact info, skills, work experience, education, projects, and certifications. Built to be the foundation that every other module in the product (matching, tailoring, cover letters) depends on.

## Why this design

Most resume parsers fail because they pick one strategy and stick with it. Pure regex/rule-based parsers (like older `pyresparser` libraries) break on creative layouts. Pure LLM parsers are expensive, slow, and hallucinate dates and titles.

This service uses **a hybrid pipeline**:

1. **Text extraction layer** — `pdfplumber` for PDFs (better layout handling than `pypdf`), `python-docx` for Word documents. Falls back to `pypdf` if `pdfplumber` chokes.
2. **Section segmentation** — heuristic detection of standard sections (Experience, Education, Skills, etc.) using header patterns and font cues.
3. **Deterministic field extraction** — email, phone, LinkedIn URL, GitHub URL extracted via regex. These are 100% reliable when present and shouldn't waste LLM tokens.
4. **LLM extraction for unstructured fields** — work experience entries, project descriptions, and skill normalization go through an LLM with strict JSON schema enforcement.
5. **Validation layer** — Pydantic models validate the LLM output; bad data is logged and the request retries once.

The result: a parser that's fast, cheap, and survives weird resume layouts.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI HTTP Layer                         │
│  POST /api/v1/parse    GET /health    GET /api/v1/parse/{id}    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ResumeParserService                          │
│  Orchestrates the full pipeline                                 │
└──┬──────────────────┬─────────────────┬─────────────────────────┘
   │                  │                 │
   ▼                  ▼                 ▼
┌─────────┐    ┌──────────────┐    ┌─────────────────┐
│ Text    │    │  Section     │    │  LLM Extractor  │
│Extractor│───▶│  Segmenter   │───▶│  (Claude/GPT)   │
└─────────┘    └──────────────┘    └────────┬────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │ Pydantic models │
                                   │   validation    │
                                   └─────────────────┘
```

## Quick start

### 1. Prerequisites

- Python 3.11+
- An Anthropic API key (recommended) or OpenAI API key

### 2. Install

```bash
git clone <your-repo-url> resume-parser-api
cd resume-parser-api
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY (or OPENAI_API_KEY)
```

### 4. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/docs> for interactive API documentation (Swagger UI).

### 5. Test it

```bash
curl -X POST http://localhost:8000/api/v1/parse \
  -F "file=@/path/to/your/resume.pdf"
```

## API Reference

### `POST /api/v1/parse`

Parse a resume file and return structured JSON.

**Request:** `multipart/form-data` with field `file` (PDF or DOCX, max 10MB).

**Response:** `200 OK` with `ParsedResume` JSON (see schema below).

**Errors:**
- `400` — invalid file type, file too large, or empty file
- `422` — file could not be parsed (corrupt or unreadable)
- `429` — rate limit exceeded
- `500` — internal error (LLM failure, etc.)

### Response schema (simplified)

```json
{
  "request_id": "uuid",
  "parsed_at": "2026-05-18T12:34:56Z",
  "personal": {
    "full_name": "Tahir Ahmed",
    "email": "tahir@example.com",
    "phone": "+92-300-1234567",
    "location": "Islamabad, Pakistan",
    "linkedin_url": "https://linkedin.com/in/tahir",
    "github_url": "https://github.com/tahir",
    "portfolio_url": null
  },
  "summary": "AI/ML Engineer with 4 years of experience...",
  "skills": {
    "technical": ["Python", "PyTorch", "LangChain", "FastAPI"],
    "soft": ["Leadership", "Communication"],
    "tools": ["Docker", "Git", "AWS"],
    "languages": ["English", "Urdu"]
  },
  "experience": [
    {
      "company": "Acme Corp",
      "title": "Senior ML Engineer",
      "location": "Remote",
      "start_date": "2023-01",
      "end_date": "Present",
      "is_current": true,
      "responsibilities": ["Built RAG system...", "Led team of 3..."],
      "technologies": ["Python", "LangChain"]
    }
  ],
  "education": [
    {
      "institution": "NUST Islamabad",
      "degree": "MS Computer Science",
      "field_of_study": "AI/ML",
      "start_date": "2024-09",
      "end_date": "2026-06",
      "gpa": "3.8"
    }
  ],
  "projects": [...],
  "certifications": [...],
  "raw_text_length": 4823,
  "extraction_warnings": []
}
```

### `GET /health`

Liveness check. Returns `{"status": "ok"}`.

## Project structure

```
resume-parser-api/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Settings (loaded from env)
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py            # HTTP endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   └── exceptions.py        # Custom exceptions
│   ├── models/
│   │   ├── __init__.py
│   │   └── resume.py            # Pydantic schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── text_extractor.py    # PDF + DOCX text extraction
│   │   ├── segmenter.py         # Section detection
│   │   ├── llm_extractor.py     # LLM-powered structured extraction
│   │   ├── regex_extractor.py   # Email, phone, URLs
│   │   └── parser_service.py    # Pipeline orchestrator
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_text_extractor.py
│   ├── test_regex_extractor.py
│   ├── test_segmenter.py
│   └── test_api.py
├── docs/
│   ├── DEPLOYMENT.md            # Render/Railway deployment guide
│   └── LINKEDIN_POST.md         # Suggested LinkedIn post when deployed
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

## Cost estimate

Per resume parsed:
- Anthropic Claude Haiku: ~$0.001–$0.003
- OpenAI GPT-4o-mini: ~$0.001–$0.002

At 10,000 resumes/month, infrastructure runs about $10–$30/month for LLM costs, plus ~$7/month for Render hosting. This is a low-cost service to operate.

## Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for step-by-step deployment to Render (free tier eligible).

## Next steps

Once this module is deployed, the next module is the **Job-Resume Matcher**, which consumes this parsed JSON to score job descriptions against the resume. The output of this service becomes the input of Module 2.

## License

MIT (for your portfolio). Add a LICENSE file before publishing publicly.

"""Shared pytest fixtures."""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from docx import Document as DocxDocument

from app.config import Settings
from app.models.resume import (
    EducationEntry,
    ExperienceEntry,
    LLMExtractionResult,
    PersonalInfo,
    Skills,
)
from app.services.parser_service import ResumeParserService


SAMPLE_RESUME_TEXT = """\
Tahir Ahmed
tahir.ahmed@example.com | +92-300-1234567 | Islamabad, Pakistan
https://linkedin.com/in/tahirahmed | https://github.com/tahirahmed

Professional Summary
AI/ML Engineer with 4 years of experience building production NLP and RAG systems.

Experience

Senior ML Engineer — Acme Corp (Remote)
January 2023 – Present
- Built a RAG-based legal chatbot using LangChain and FastAPI serving 10k+ queries/day.
- Led a team of 3 engineers to deliver a federated learning prototype on time.
- Reduced model inference cost by 40% through quantization and caching.

ML Engineer — Beta Labs (Lahore, Pakistan)
June 2021 – December 2022
- Developed CNN-LSTM-Attention model for Parkinson's classification (91% accuracy).
- Mentored 2 junior engineers on PyTorch best practices.

Education

MS in Computer Science — NUST Islamabad
September 2024 – June 2026
GPA: 3.8/4.0

BE in Electrical Engineering — NUST Islamabad
September 2017 – June 2021

Skills
Python, PyTorch, TensorFlow, LangChain, FastAPI, Docker, AWS, Git, English, Urdu

Projects

Legal Chatbot
Built an LLM-powered legal Q&A system using RAG and LangChain.
Technologies: Python, LangChain, FastAPI, Docker

Certifications
AWS Certified Machine Learning Specialty — Amazon, 2024
"""


@pytest.fixture
def sample_resume_text() -> str:
    return SAMPLE_RESUME_TEXT


@pytest.fixture
def sample_docx_bytes() -> bytes:
    """A minimal DOCX file containing the sample resume text."""
    doc = DocxDocument()
    for line in SAMPLE_RESUME_TEXT.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def fake_llm_result() -> LLMExtractionResult:
    """A handcrafted LLMExtractionResult matching the sample resume."""
    return LLMExtractionResult(
        personal=PersonalInfo(
            full_name="Tahir Ahmed",
            email="tahir.ahmed@example.com",
            phone="+92-300-1234567",
            location="Islamabad, Pakistan",
            linkedin_url="https://linkedin.com/in/tahirahmed",
            github_url="https://github.com/tahirahmed",
        ),
        summary="AI/ML Engineer with 4 years of experience building production NLP and RAG systems.",
        skills=Skills(
            technical=["Python", "PyTorch", "TensorFlow", "LangChain", "FastAPI"],
            tools=["Docker", "AWS", "Git"],
            languages=["English", "Urdu"],
        ),
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Senior ML Engineer",
                location="Remote",
                start_date="2023-01",
                end_date="Present",
                is_current=True,
                responsibilities=[
                    "Built a RAG-based legal chatbot using LangChain and FastAPI serving 10k+ queries/day.",
                ],
            ),
        ],
        education=[
            EducationEntry(
                institution="NUST Islamabad",
                degree="MS in Computer Science",
                start_date="2024-09",
                end_date="2026-06",
                gpa="3.8/4.0",
            ),
        ],
    )


@pytest.fixture
def test_settings() -> Settings:
    """Settings configured to bypass real LLM calls in tests."""
    return Settings(
        llm_provider="gemini",
        gemini_api_key="test-key-not-real",
        app_env="development",
        log_level="WARNING",
    )


@pytest.fixture
def parser_with_fake_llm(test_settings, fake_llm_result):
    """A ResumeParserService whose LLMExtractor is mocked to return a fixed result."""
    fake_llm = MagicMock()
    fake_llm.extract.return_value = fake_llm_result
    return ResumeParserService(settings=test_settings, llm_extractor=fake_llm)

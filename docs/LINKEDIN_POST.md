# Suggested LinkedIn post

Once your service is deployed and live, post this on LinkedIn. This is the first build-in-public moment for the AI Job Application Tracker product.

---

## Version A — Technical, for engineering audience

🛠️ Just shipped Module 1 of my new project: a Resume Parser API.

I'm building an AI Job Application Tracker — a tool that watches job boards, matches openings against your resume, generates tailored applications, and tracks every step. Module 1 is the foundation: turn a PDF or DOCX resume into clean structured JSON.

The interesting design choices:

🔹 Hybrid pipeline, not pure LLM. Regex handles email/phone/LinkedIn (deterministic, no hallucinations). The LLM handles the messy stuff — experience, skills, projects.

🔹 Source-bound extraction. The LLM is explicitly instructed never to invent information. If a field isn't in the resume, it stays null. No more hallucinated dates or fake job titles.

🔹 Provider-agnostic. Swap between Anthropic and OpenAI with one env var. Future-proofs the whole system.

🔹 Force-JSON via tool use (Anthropic) or response_format (OpenAI). Eliminates 99% of malformed JSON issues.

Tech stack: FastAPI + pdfplumber + python-docx + Pydantic + Claude Haiku 4.5.

Live API: [your-url]/docs
Code: [your-github-url]

Module 2 is the matcher — turning these structured resumes into match scores against live job descriptions. Building this in public, one piece at a time.

What would you want to see this tool do that current job-search tools can't?

#AI #FastAPI #BuildInPublic #IndieDev #LangChain

---

## Version B — Outcome-focused, for broader audience

Job hunting in 2026 is brutal.

97% of companies use ATS to screen resumes. 88% of qualified candidates get filtered out before a human ever sees them. A properly tailored application takes 4–6 hours. Doing 30 of them is a full-time month.

So I'm building a tool to fix it.

The AI Job Application Tracker watches LinkedIn, Indeed, and Glassdoor for openings that match your background, generates a tailored resume and cover letter for each one, and queues them for your approval — never the other way around. You stay in control. The AI does the grunt work.

This week I shipped Module 1: the engine that reads any PDF or DOCX resume and converts it into clean structured data. It's the foundation everything else stands on.

Demo & docs: [your-url]/docs
GitHub: [your-github-url]

I'm building this in public over the next 6 weeks. Follow along if you want to see how the matching engine, the Chrome extension, and the auto-apply flow come together — or if you just want a job-search tool that doesn't suck.

What's your worst job-search horror story? Tell me in the comments and I'll see if Module 4 (the cover letter generator) can fix it.

---

## Version C — Short, casual

Shipped the first piece of something I've been wanting to exist for a long time.

A resume parser that actually works on weird layouts, doesn't hallucinate fake job titles, and turns any PDF into clean JSON in under 3 seconds.

It's Module 1 of an AI Job Application Tracker I'm building over the next 6 weeks. Open source, deployed live, full docs at the link.

Watch this space.

[your-url]

#BuildInPublic #AI

---

## Tips for posting

1. **Post Version A or B during weekday business hours** (Tue–Thu, 9am–11am in your target market's timezone) for max reach.
2. **Add a screenshot of the /docs page.** LinkedIn boosts posts with images significantly.
3. **Tag 2–3 people** who might engage (other AI builders, friends from NUST).
4. **Reply to every comment in the first hour.** Algorithm rewards conversation.
5. **Don't ask for follows.** Ask a question that invites discussion (last line of each version does this).

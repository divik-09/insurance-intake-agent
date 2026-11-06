# Insurance Intake Agent

An email-driven AI agent that turns a small business's messy quote request into a complete, validated
submission, asks the customer for *only* what is missing, and then submits the finished request to a
carrier quote portal.

```
"Hi, I own Sweet Crumbs Bakery in Columbus, Ohio. 6 employees. Need GL and workers' comp."
        │
        ▼   extract (LLM → validated schema) · merge into case · find what's missing
"Thanks! I just need: 1. your approximate annual revenue."
        │
"About $450,000 last year."
        ▼   complete → fill carrier portal form (with retries) → store quote
"Good news — indicative quote Q-9D512BF6, estimated premium $3,617.90."
```

Built with **Python · FastAPI · SQLAlchemy · Pydantic · Anthropic / OpenAI APIs · Playwright**.

> **Scope note.** The carrier portal is a *mock* served by this app (clearly fake premium formula) so the
> automation is realistic without touching any real insurer. Email transport is a webhook
> (`POST /inbound`), not a live mailbox integration.

## How it works

```mermaid
flowchart LR
    E[Inbound email<br/>POST /inbound] --> S[IntakeService]
    S -->|1. find / open case| DB[(SQLite or Postgres)]
    S -->|2. extract| L[LLM client<br/>Anthropic · OpenAI · regex baseline]
    L -->|raw JSON| V[Pydantic validation<br/>field-by-field salvage]
    V -->|merge with known fields| S
    S -->|missing fields| F[Follow-up email]
    S -->|complete| P[Portal driver<br/>Playwright or HTTP<br/>+ retry/backoff]
    P --> M[Mock carrier portal<br/>/portal/quote]
    P -->|quote| S
    S -->|confirmation / holding message| O[Outbound email]
```

| Piece | File | What it does |
|---|---|---|
| Schema | `app/schemas.py` | `Submission` model, required fields, state normalization, defensive `safe_submission` |
| LLM clients | `app/llm.py` | Anthropic (forced tool use), OpenAI (JSON mode), regex baseline — one interface |
| Baseline | `app/heuristics.py` | Offline regex extractor for tests, CI and as an eval floor |
| Extraction | `app/extraction.py` | Run LLM → validate → merge into what we already knew |
| Follow-ups | `app/followup.py` | Templated replies asking for exactly the missing fields |
| Orchestration | `app/service.py` | The conversation state machine, retries, failure handling |
| Storage | `app/db.py` | `cases`, `messages`, `portal_runs` tables |
| Portal + automation | `app/portal_app.py`, `app/portal_client.py` | Mock portal; Playwright and HTTP drivers |
| API | `app/main.py` | FastAPI endpoints |
| Evals | `evals/run_eval.py`, `data/test_emails.jsonl` | Per-field accuracy on 20 labelled emails |

## Quick start

```bash
git clone https://github.com/<your-username>/insurance-intake-agent.git
cd insurance-intake-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m scripts.demo        # full two-email conversation, offline, no API key
python -m pytest              # test suite
python -m evals.run_eval      # extraction accuracy (regex baseline)
```

Run the API:

```bash
uvicorn app.main:create_app --factory --port 8000
# docs at http://127.0.0.1:8000/docs  ·  mock portal form at http://127.0.0.1:8000/portal/quote
```

```bash
curl -s -X POST localhost:8000/inbound -H 'content-type: application/json' -d '{
  "sender_email": "owner@sweetcrumbs.com",
  "body": "I own Sweet Crumbs Bakery in Columbus, Ohio. 6 employees. Need general liability and workers comp."
}'
# -> status "collecting", missing ["annual_revenue"], and the follow-up email in "reply"
```

### Use a real LLM

```bash
cp .env.example .env     # then set:
# LLM_PROVIDER=anthropic   (or openai)
# ANTHROPIC_API_KEY=...    (or OPENAI_API_KEY=...)
```

### Optional: real-browser portal automation

```bash
pip install -r requirements-browser.txt && playwright install chromium
# PORTAL_DRIVER=auto picks Playwright when a browser is installed, otherwise HTTP
python -m pytest tests/test_playwright_driver.py     # runs only when Chromium is present
```

### Optional: Postgres / Supabase

```bash
pip install -r requirements-postgres.txt
# DATABASE_URL=postgresql+psycopg://user:password@host:5432/postgres
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/inbound` | Process one inbound email → returns status, missing fields, reply, quote |
| `GET` | `/cases`, `/cases/{id}` | List cases / full case with message thread and portal attempts |
| `POST` | `/cases/{id}/retry-portal` | Re-run the portal step for a case stuck in `portal_failed` |
| `GET` | `/health` | Liveness + which LLM and portal driver are active |
| `GET/POST` | `/portal/quote` | The mock carrier portal |

Set `API_KEY` to require an `X-API-Key` header on everything except `/health` and `/portal`.

Case lifecycle: `collecting → ready → submitted`, or `ready → portal_failed → (retry) → submitted`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `heuristic` | `heuristic`, `anthropic`, or `openai` |
| `LLM_MODEL` | provider default | Override the model name |
| `DATABASE_URL` | `sqlite:///./intake.db` | Any SQLAlchemy URL |
| `PORTAL_DRIVER` | `auto` | `auto`, `http`, or `playwright` |
| `PORTAL_BASE_URL` | `http://127.0.0.1:8000` | Where the automation reaches the portal |
| `PORTAL_MAX_ATTEMPTS` | `3` | Tries per submission (exponential backoff) |
| `PORTAL_FAILURE_RATE` | `0.0` | Fraction of portal requests that fail on purpose, to watch retries work |
| `API_KEY` | unset | Enables API-key auth |

## Evaluation

`python -m evals.run_eval --provider <heuristic|anthropic|openai>` scores extraction field by field on
20 labelled emails. "Not stated" counts as a real answer: returning `null` for a missing revenue is
correct, inventing a number is wrong.

Regex baseline, as measured by `python -m evals.run_eval --provider heuristic`:

```
Provider: heuristic   Model: regex-baseline   Emails: 20
----------------------------------------------------
business_name       85.0%
industry            90.0%
state              100.0%
employee_count      80.0%
annual_revenue     100.0%
coverage_types      95.0%
----------------------------------------------------
OVERALL (fields)    91.7%  (110/120)
Fully correct      14/20 emails
```

The baseline's misses are instructive: it can't add up "eight drivers and two office staff", can't read
"just me and one stylist" as 2 people, and doesn't understand negation ("we *don't* need workers comp").
Those are the cases an LLM should win on.

| Extractor | Overall field accuracy | Fully correct emails |
|---|---|---|
| Regex baseline | 91.7% (110/120) | 14/20 |
| LLM (`anthropic`) | _run the eval with your API key and record it here_ | |
| LLM (`openai`) | _run the eval with your API key and record it here_ | |

**Caveats, stated plainly:** the 20 emails were written by the author for this project (synthetic, not
real customer mail), so treat them as a regression suite, not a benchmark. The LLM rows are blank
until measured.

## Design decisions

- **Validation is the trust boundary.** LLM output is untrusted. Each field is validated independently, so
  one hallucinated value (say, `state: "Narnia"`) drops that field instead of discarding the whole email.
- **Forced structured output.** The Anthropic client uses forced tool use with a JSON schema; the prompt
  tells the model the email is untrusted data and to ignore instructions inside it.
- **Merge, don't overwrite.** Each email only fills or corrects fields; `null` never erases something known.
- **Ask for exactly what's missing.** Replies are templated, so customer-facing text is predictable and
  reviewable; the LLM is used only where judgment is needed.
- **No transaction held across slow calls.** The DB session is closed before calling the LLM or portal.
- **Failures are first-class.** Portal retries use exponential backoff; if they're exhausted the case moves to
  `portal_failed`, the customer gets an honest holding message, and `/retry-portal` can recover it. An LLM
  outage degrades to "ask the customer" instead of crashing.
- **Idempotent submission.** A `submitted` case is never sent to the portal twice.
- **Swappable parts.** LLM, portal driver, and database are injected, which is what makes the whole flow
  testable offline.

## Testing

`python -m pytest` runs 66 tests offline: schema validation, extractors, merge logic, LLM-client parsing
(with fake clients), retry/backoff timing, the mock portal and HTTP driver, the full conversation flow, retry
and recovery paths, API validation, and API-key auth. One browser test is skipped unless Chromium is installed.

## Known limitations

- The Playwright driver is implemented, but it was **not run** in the environment this was developed in
  (the Chromium download was unavailable there). Run `tests/test_playwright_driver.py` locally to verify it.
- Postgres/Supabase is supported through `DATABASE_URL` but the tests run on SQLite only.
- Conversations are matched by sender address; two simultaneous emails for the same case could race.
  Production would add row locking or a queue.
- No real mailbox integration, no PII redaction, and customer emails are sent to the chosen LLM provider.
- The premium formula is a toy. Real carrier portals add logins, CAPTCHAs, and changing page structure.

## Roadmap

Real inbound/outbound email via a provider webhook · background queue for portal submissions · multiple
carriers with per-carrier drivers · attachments (loss runs, ACORD forms) · human-review queue for
`portal_failed` cases · OpenTelemetry tracing.

## License

MIT — see `LICENSE`.

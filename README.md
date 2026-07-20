# 🤝 Startup Partner Fit Analyzer

A small web app that evaluates a startup as a potential **technology partner for
Siemens Digital Industries Software (DISW)**, using an LLM agent and public
sources only.

**Live app:** https://startup-partner-********************

Enter a startup's URL (e.g. `https://www.manukai.ch/`) and the app returns a
product summary, a comparison against the Siemens DISW portfolio, a partner-fit
score of 1–10, and short justifications.

---

## What it does

1. An **agent** reads the startup's public website and decides which pages to open.
2. It **summarizes** the main product offering in one paragraph.
3. It **compares** that offering against the Siemens DISW portfolio.
4. It **scores** partner fit from 1 to 10 against an explicit rubric.
5. It **justifies** the score with 3–5 bullets, each naming specific DISW products.

## How it works

```
URL → fetch homepage → agent loop (model picks pages) → product summary
                                                            ↓
                          score + justifications ← compare vs DISW portfolio
```

### The agent loop

The model is given the homepage text plus the list of internal links, and replies
with **one of two JSON actions**:

```json
{"action": "read",   "url": "https://..."}
{"action": "finish", "summary": "..."}
```

If it asks to read a page, the code fetches it and feeds the text back. The model
decides *which* pages are worth reading; the **code enforces the boundaries**:

| Guardrail | Value |
|---|---|
| Same site only (subdomains allowed) | `_same_site()` |
| Extra pages beyond the homepage | 3 |
| Loop turns | 8 |
| Characters per page | 6,000 |
| Must read ≥1 deep page before summarizing | enforced in code |

That last rule exists because in early testing the agent summarized from the
homepage alone — which is marketing copy. The prompt asks for a deeper page, and
the code **rejects** a summary based only on the homepage. A prompt is a request;
code is a rule.

### Scoring rubric

The score measures **partner fit, not product quality**. It is anchored so the
result is repeatable rather than a vibe:

| Score | Meaning |
|---|---|
| 9–10 | Direct synergy: fills a clear portfolio gap, obvious integration path |
| 7–8 | Complementary industrial technology, plausible integration with ≥1 product line |
| 4–6 | Some relevance, unclear integration path, or partially competes |
| 1–3 | Different market, no technological connection, or a head-on competitor |

A product that duplicates a DISW product scores **low** — a direct competitor is a
poor partner, however good the product is.

The model must also emit a `relationship` field (`complementary` / `overlapping` /
`unrelated` / `mixed`) **before** the number, which anchors the score to a stated
category. The response is then **validated in code** (types, score range, non-empty
justifications); on failure the exact validation error is sent back for one retry.

## Tools and decisions

| Choice | Why | Alternative rejected |
|---|---|---|
| Python + Streamlit | Task explicitly asked for minimal UI; a web app in pure Python | Flask/React — effort on the part declared unimportant |
| Groq + `llama-3.3-70b-versatile` | Free, fast, already familiar | An API key was offered by Siemens; not needed |
| `requests` + BeautifulSoup | Verified upfront that the example sites serve static HTML | Headless browser — heavy and unnecessary here |
| Hand-rolled agent loop | Every line is explainable | LangChain — hides the mechanics |
| Static Siemens context | Reliable, token-cheap, still public sources | Live scraping of siemens.com |

The Siemens portfolio summary in `siemens_context.py` was curated from live public
pages rather than from model memory — which turned out to matter, since the design
portfolio is now branded **Designcenter** and **Altair** (2025) sits alongside
Simcenter. A summary written from memory would have described an outdated lineup.

## Security and robustness

| Risk | Mitigation |
|---|---|
| **SSRF** (internal IPs, cloud metadata) | Every fetch resolves DNS and requires a **public** IP (`ipaddress.is_global`), re-checked after redirects |
| Non-HTML targets (PDFs) | `Content-Type` check before reading the body, 2 MB download cap |
| Duplicate page reads | URL canonicalization drops query strings (`utm_*`), fragments, trailing slashes |
| Subdomain pages missed | Same-site check accepts `docs.startup.com` but rejects `evilstartup.com` |
| **Prompt injection** from scraped text | Website text is wrapped in delimiters, the delimiters are scrubbed from the text, and both prompts state that website text is untrusted **data, not instructions** |
| Non-English websites | Both prompts require English output (verified on a German site) |

All of the above use the Python standard library only — no new dependencies.

## Limitations (deliberate)

- **The score is an LLM judgment against a rubric I defined**, not an objective
  metric. The rubric, the enforcement, and the required justifications are the
  contribution — not the number itself.
- **The Siemens context is static** and can go stale as the portfolio changes.
- **Designed for startups** — a company with one main product offering. Given a
  large conglomerate's portal it will faithfully summarize whatever that site
  currently promotes, which is not a useful "main product".
- **JavaScript-heavy sites** that render content client-side are not supported.
- **Residual prompt-injection risk**: a site could still bias the score with
  instruction-like text. There is no airtight prompt-level defence; the structural
  guards (JSON-only protocol, code validation, domain limits) are the real
  protection.
- This is **targeted hardening**, not a full production service — no rate
  limiting, authentication, logging, or monitoring.

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Add your Groq API key to `.streamlit/secrets.toml` (gitignored):

```toml
GROQ_API_KEY = "gsk_..."
```

Then:

```bash
.venv/bin/python -m streamlit run app.py
```

On Streamlit Community Cloud the same key goes into the app's **Secrets** setting —
no code change required.

## Project structure

```
app.py               Streamlit UI
agent.py             Fetching, the agent loop, comparison, validation
prompts.py           System prompts and the scoring rubric
siemens_context.py   Curated Siemens DISW portfolio + source links
```

`agent.py` has no knowledge of Streamlit: it reports progress through an
`on_event` callback that the UI wires to `st.write`. The same agent therefore runs
from the terminal for testing, which is how it was developed.

## Testing

Verified against both example startups, a deliberately irrelevant control, and a
German-language site:

| Site | Result |
|---|---|
| manukai.ch (AI for CNC programming) | 8/10 — complementary (NX/CAM, Tecnomatix, Opcenter) |
| protex.ai (industrial safety AI) | 8/10 — complementary (Insights Hub, Opcenter) |
| wolt.com (food delivery — control) | 1/10 — unrelated |
| sipgate.de (German) | English output |

The irrelevant control matters: it shows the score can go **down**, not just that
the happy path works.

---

Built as a home assignment for Siemens. Planned and built with an AI coding
assistant under my direction; every decision here is one I can explain.

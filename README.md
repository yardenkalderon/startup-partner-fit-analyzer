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
6. It **ranks similarity** to Siemens' publicly named Xcelerator partners, and
   names the ones the startup most resembles.

## How it works

```
URL → fetch homepage → agent loop (model picks pages) → product summary
                                                            │
                        ┌───────────────────────────────────┴──────────┐
                        ▼                                              ▼
        compare vs DISW portfolio                     compare vs existing partners
        → fit score + justifications                  → similarity score + closest partners
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
| Extra pages beyond the homepage | 2 |
| Loop turns | 8 |
| Characters per page | 3,500 |
| Must read ≥1 deep page before summarizing | enforced in code |

That last rule exists because a homepage is marketing copy. The prompt asks for a
deeper page, and the code **rejects** a summary based only on the homepage. A
prompt is a request; code is a rule.

Fetching is restricted to public hosts and HTML pages, with a download cap, and
scraped text is passed to the model as clearly delimited untrusted data.

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

### Similarity to existing partners

A second, independent question: *does this startup look like the companies Siemens
already partners with?* The reference set is the publicly named Xcelerator partners
(NVIDIA, Microsoft, AWS, SAP, Bentley, Accenture, Atos, Deloitte) with the role each
plays, curated in `siemens_context.py`.

The rubric here deliberately judges **technology domain, integration pattern and
customer base — never company size, revenue or maturity**. A three-person startup
can score 10 if its technology fits an established partner archetype. Without that
instruction the comparison would degenerate into "you are not as big as Microsoft".

## Tools and decisions

| Choice | Why |
|---|---|
| Python + Streamlit | The task asked for a minimal UI; a web app in pure Python |
| Groq, `openai/gpt-oss-120b` | Free tier, fast, per-model quota |
| `requests` + BeautifulSoup | The example sites serve static HTML |
| Hand-rolled agent loop | Every line is explainable |
| Static Siemens context | Reliable, token-cheap, still public sources |

The Siemens portfolio summary in `siemens_context.py` was curated from live public
pages rather than from model memory — which turned out to matter, since the design
portfolio is now branded **Designcenter** and **Altair** (2025) sits alongside
Simcenter. A summary written from memory would have described an outdated lineup.

### Provider abstraction

Every model call goes through one function, and both supported providers speak the
same OpenAI-compatible protocol, so **the provider is a config entry rather than a
rewrite** (`PROVIDERS` in `agent.py`). Note that "OpenAI-compatible" describes a
request format, not the vendor: requests go to Groq's or Google's servers.

### Caching

Results are cached per URL (`st.cache_data`), so re-analyzing a startup returns
instantly and costs no API tokens. The cache is keyed on the URL, not on the code
version — reboot the app after a code change to clear it.

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Add an API key to `.streamlit/secrets.toml` (gitignored):

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
app.py               Streamlit UI, result caching, error handling
agent.py             Provider config, fetching, the agent loop, scoring, validation
prompts.py           System prompts and both scoring rubrics
siemens_context.py   Curated Siemens DISW portfolio + partner list + source links
```

`agent.py` has no knowledge of Streamlit: it reports progress through an
`on_event` callback that the UI wires to `st.write`. The same agent therefore runs
from the terminal for testing, which is how it was developed.

## Testing

Verified against both example startups, two discrimination controls, and a
German-language site:

| Site | Fit | Similarity | Note |
|---|---|---|---|
| manukai.ch (AI for CNC programming) | 8/10 complementary | 8/10 | NX/CAM, Tecnomatix, Opcenter |
| protex.ai (industrial safety AI) | 8/10 complementary | 8/10 | Insights Hub, Opcenter, Mendix |
| enso.bot (AI marketing agents) | **2/10 unrelated** | 5/10 | Control: AI software, wrong domain |
| wolt.com (food delivery) | **1/10 unrelated** | 2/10 | Control: obviously irrelevant |
| sipgate.de (German) | — | — | English output confirmed |

The controls matter more than the successes. `wolt.com` shows the score can go
down at all; `enso.bot` is the harder test — an AI software company that sounds
relevant on the surface, correctly scored low because its domain is marketing
rather than industrial engineering.

---

Built as a home assignment for Siemens. Planned and built with an AI coding
assistant under my direction; every decision here is one I can explain.

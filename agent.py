import ipaddress
import json
import os
import re
import socket
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

from prompts import (
    COMPARE_SYSTEM,
    PARTNER_SYSTEM,
    RESEARCH_SYSTEM,
    compare_user_msg,
    partner_user_msg,
    research_user_msg,
)
from siemens_context import SIEMENS_DISW_CONTEXT, SIEMENS_PARTNERS

# Both providers expose an OpenAI-compatible chat-completions endpoint, so one
# client library serves both and switching providers is a config change.
#
# Groq is the active provider. Gemini was measured as an alternative and
# rejected: gemini-3.5-flash's free tier allows only 20 requests/day, which is
# roughly 4 analyses — worse than Groq's 100k tokens/day. Kept here documented
# so the comparison is reproducible.
PROVIDERS = {
    "gemini": {
        "secret": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.5-flash",
        # Gemini's newer models think before answering and those thinking tokens
        # count against max_tokens — at the default budget the JSON was truncated
        # mid-string. "low" effort also cuts latency from ~32s to ~3s per call.
        "extra": {"reasoning_effort": "low"},
    },
    "groq": {
        "secret": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "extra": {},
    },
}
PROVIDER_ORDER = ["groq", "gemini"]

MAX_OUTPUT_TOKENS = 2000  # must cover thinking tokens, not just the JSON reply
FETCH_TIMEOUT = 15
MAX_DOWNLOAD_BYTES = 2_000_000  # cap page downloads; a PDF/huge file gets cut off
# The agent loop resends the whole conversation on every turn, so page text is
# the dominant token cost. Product info sits at the top of a page, so truncating
# costs little.
MAX_PAGE_CHARS = 3500
MAX_AGENT_PAGES = 2    # extra pages the agent may read beyond the homepage
MAX_AGENT_TURNS = 8
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class LLM(NamedTuple):
    """An LLM endpoint: which client to call, which model, and provider quirks."""

    client: OpenAI
    model: str
    extra: dict
    provider: str


def _get_secret(name: str) -> str | None:
    # Local dev reads .streamlit/secrets.toml (gitignored); Streamlit Cloud
    # reads the same names from the app's Secrets settings.
    try:
        value = st.secrets.get(name, "")
    except FileNotFoundError:
        value = ""
    return value or os.environ.get(name) or None


def get_client() -> LLM | None:
    """Return the first configured provider, preferring Gemini."""
    for provider in PROVIDER_ORDER:
        config = PROVIDERS[provider]
        key = _get_secret(config["secret"])
        if key:
            return LLM(
                client=OpenAI(api_key=key, base_url=config["base_url"]),
                model=config["model"],
                extra=config["extra"],
                provider=provider,
            )
    return None


def ping(llm: LLM) -> str:
    """Minimal call that verifies the API key and model are working."""
    resp = llm.client.chat.completions.create(
        model=llm.model,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0,
        **llm.extra,
    )
    return resp.choices[0].message.content.strip()


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _canonical(url: str) -> str:
    """Normalize a URL for dedup: drop query (utm_* etc.), fragment, trailing slash."""
    p = urlparse(url)
    return f"{p.scheme}://{(p.netloc or '').lower()}{p.path}".rstrip("/")


def _same_site(url: str, base_url: str) -> bool:
    """True for the same domain or a subdomain (docs.startup.com of startup.com)."""
    d, b = _domain(url), _domain(base_url)
    return d == b or d.endswith("." + b)


def _assert_public_url(url: str) -> None:
    """SSRF guard: only http(s) to hosts that resolve to public IPs."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed.")
    host = p.hostname or ""
    if not host or host == "localhost" or host.endswith(".local"):
        raise ValueError("Blocked non-public host.")
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise ValueError(f"Could not resolve host: {host}")
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    if any(not ip.is_global for ip in ips):
        raise ValueError("Blocked non-public address.")


def fetch_page(url: str) -> tuple[str, list[str]]:
    """Return (visible text, same-site links) of an HTML page.

    Raises ValueError for blocked or non-HTML targets, requests.RequestException
    for network errors.
    """
    _assert_public_url(url)
    resp = requests.get(
        url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}, stream=True
    )
    resp.raise_for_status()
    _assert_public_url(resp.url)  # re-check after redirects
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype.lower():
        resp.close()
        raise ValueError(f"Not an HTML page (Content-Type: {ctype or 'unknown'}).")
    # Accumulate chunks up to the cap. iter_content yields whatever arrived on
    # the wire, so reading a single chunk truncates large pages to a fragment —
    # which silently produced near-empty page text instead of an error.
    chunks: list[bytes] = []
    downloaded = 0
    for chunk in resp.iter_content(65536):
        chunks.append(chunk)
        downloaded += len(chunk)
        if downloaded >= MAX_DOWNLOAD_BYTES:
            break
    resp.close()
    html = b"".join(chunks)[:MAX_DOWNLOAD_BYTES].decode(
        resp.encoding or "utf-8", errors="replace"
    )

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    text = re.sub(r"[<>]{3,}", " ", text)  # scrub our prompt delimiters from page text
    text = text[:MAX_PAGE_CHARS]

    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(url, a["href"]))
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https") and _same_site(href, url):
            if href and href != _canonical(url) and href not in links:
                links.append(href)
    return text, links[:40]


def _chat_json(llm: LLM, messages: list[dict]) -> tuple[dict | None, str]:
    resp = llm.client.chat.completions.create(
        model=llm.model,
        messages=messages,
        temperature=0.2,
        max_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_object"},
        **llm.extra,
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return None, raw


def run_research_agent(llm: LLM, url: str, on_event=lambda msg: None) -> dict:
    """Agent loop: the model decides which pages of the startup's site to read;
    our code enforces the guardrails (same domain, page cap, turn cap).

    Returns {"summary": str, "pages_read": list[str]}.
    """
    url = normalize_url(url)
    on_event(f"Reading homepage: {url}")
    text, links = fetch_page(url)
    pages_read = [url]

    messages = [
        {"role": "system", "content": RESEARCH_SYSTEM},
        {"role": "user", "content": research_user_msg(url, text, links)},
    ]

    for _ in range(MAX_AGENT_TURNS):
        reply, raw = _chat_json(llm, messages)
        messages.append({"role": "assistant", "content": raw})

        if reply and reply.get("action") == "finish" and reply.get("summary"):
            if len(pages_read) == 1 and links:
                # Don't accept a summary based on the homepage alone
                messages.append(
                    {
                        "role": "user",
                        "content": "Not yet — first read at least one product/solutions page from the links list.",
                    }
                )
                continue
            on_event("Agent has enough information — done reading")
            return {"summary": str(reply["summary"]).strip(), "pages_read": pages_read}

        if reply and reply.get("action") == "read" and reply.get("url"):
            page = _canonical(normalize_url(str(reply["url"])))
            if len(pages_read) > MAX_AGENT_PAGES:
                feedback = "Page limit reached. Respond with the finish action now."
            elif not _same_site(page, url):
                feedback = f"{page} is outside the startup's website. Pick a link from the list or finish."
            elif page in (_canonical(p) for p in pages_read):
                feedback = f"You already read {page}. Pick a different link or finish."
            else:
                on_event(f"Agent chose to read: {page}")
                try:
                    page_text, _ = fetch_page(page)
                    pages_read.append(page)
                    feedback = (
                        f"Visible text of {page}:\n"
                        f"<<<WEBSITE TEXT>>>\n{page_text}\n<<<END WEBSITE TEXT>>>"
                    )
                except (requests.RequestException, ValueError) as exc:
                    feedback = (
                        f"Could not read {page} ({exc}). "
                        "Pick a different link or finish."
                    )
        else:
            feedback = "Invalid response. Reply only with one of the two JSON actions you were given."

        messages.append({"role": "user", "content": feedback})

    # Out of turns — force a final summary so the run still produces a result
    on_event("Turn limit reached — asking the agent to summarize now")
    messages.append(
        {
            "role": "user",
            "content": 'Respond now with {"action": "finish", "summary": "..."} based on what you have read.',
        }
    )
    reply, _ = _chat_json(llm, messages)
    if reply and reply.get("summary"):
        return {"summary": str(reply["summary"]).strip(), "pages_read": pages_read}
    raise RuntimeError("The agent did not produce a summary. Try again.")


VALID_RELATIONSHIPS = {"complementary", "overlapping", "unrelated", "mixed"}


def _check_text(reply: dict, field: str) -> str | None:
    if not isinstance(reply.get(field), str) or not reply[field].strip():
        return f"missing '{field}' text"
    return None


def _check_score(reply: dict, field: str) -> str | None:
    score = reply.get(field)
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
        return f"'{field}' must be an integer between 1 and 10"
    return None


def _check_str_list(reply: dict, field: str) -> str | None:
    values = reply.get(field)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(v, str) and v.strip() for v in values)
    ):
        return f"'{field}' must be a non-empty list of strings"
    return None


def _coerce_score(reply: dict | None, field: str) -> None:
    """Accept a float or numeric string where the prompt asked for an integer."""
    if not isinstance(reply, dict):
        return
    score = reply.get(field)
    if isinstance(score, float) and score.is_integer():
        reply[field] = int(score)
    elif isinstance(score, str) and score.strip().isdigit():
        reply[field] = int(score.strip())


def _validate_comparison(reply: dict | None) -> str | None:
    """Return an error message describing what is wrong, or None if valid."""
    if not isinstance(reply, dict):
        return "not a JSON object"
    if reply.get("relationship") not in VALID_RELATIONSHIPS:
        return "'relationship' must be one of: complementary, overlapping, unrelated, mixed"
    return (
        _check_text(reply, "comparison")
        or _check_score(reply, "score")
        or _check_str_list(reply, "justifications")
    )


def _validate_partner(reply: dict | None) -> str | None:
    if not isinstance(reply, dict):
        return "not a JSON object"
    return (
        _check_str_list(reply, "closest_partners")
        or _check_text(reply, "similarity_comparison")
        or _check_score(reply, "similarity_score")
        or _check_str_list(reply, "similarity_justifications")
    )


def _run_scored_call(llm: LLM, system: str, user: str, validate, score_field: str) -> dict:
    """One focused call whose JSON reply is validated in code.

    On failure the exact validation error is fed back to the model for one retry.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    error = "no attempt"
    for _ in range(2):
        reply, raw = _chat_json(llm, messages)
        _coerce_score(reply, score_field)
        error = validate(reply)
        if error is None:
            return reply
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": f"Invalid response ({error}). Return the corrected JSON object only.",
            }
        )
    raise RuntimeError(f"Model output failed validation twice ({error}).")


def run_comparison(llm: LLM, startup_summary: str) -> dict:
    """Compare the startup to the DISW product portfolio and score partner fit."""
    return _run_scored_call(
        llm,
        COMPARE_SYSTEM,
        compare_user_msg(startup_summary, SIEMENS_DISW_CONTEXT),
        _validate_comparison,
        "score",
    )


def run_partner_similarity(llm: LLM, startup_summary: str) -> dict:
    """Score how closely the startup resembles Siemens' existing partners."""
    return _run_scored_call(
        llm,
        PARTNER_SYSTEM,
        partner_user_msg(startup_summary, SIEMENS_PARTNERS),
        _validate_partner,
        "similarity_score",
    )

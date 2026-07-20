import ipaddress
import json
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from groq import Groq

from prompts import COMPARE_SYSTEM, RESEARCH_SYSTEM, compare_user_msg, research_user_msg
from siemens_context import SIEMENS_DISW_CONTEXT

MODEL = "llama-3.3-70b-versatile"
FETCH_TIMEOUT = 15
MAX_DOWNLOAD_BYTES = 2_000_000  # cap page downloads; a PDF/huge file gets cut off
MAX_PAGE_CHARS = 6000  # keeps the whole conversation inside free-tier token limits
MAX_AGENT_PAGES = 3    # extra pages the agent may read beyond the homepage
MAX_AGENT_TURNS = 8
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _get_api_key() -> str | None:
    # Local dev reads .streamlit/secrets.toml (gitignored); Community Cloud
    # reads the same name from the app's Secrets settings.
    try:
        key = st.secrets.get("GROQ_API_KEY", "")
    except FileNotFoundError:
        key = ""
    return key or os.environ.get("GROQ_API_KEY") or None


def get_client() -> Groq | None:
    key = _get_api_key()
    return Groq(api_key=key) if key else None


def ping(client: Groq) -> str:
    """Minimal call that verifies the API key and model are working."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_tokens=5,
        temperature=0,
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
    raw = next(resp.iter_content(MAX_DOWNLOAD_BYTES), b"")
    html = raw.decode(resp.encoding or "utf-8", errors="replace")

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


def _chat_json(client: Groq, messages: list[dict]) -> tuple[dict | None, str]:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return None, raw


def run_research_agent(client: Groq, url: str, on_event=lambda msg: None) -> dict:
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
        reply, raw = _chat_json(client, messages)
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
    reply, _ = _chat_json(client, messages)
    if reply and reply.get("summary"):
        return {"summary": str(reply["summary"]).strip(), "pages_read": pages_read}
    raise RuntimeError("The agent did not produce a summary. Try again.")


VALID_RELATIONSHIPS = {"complementary", "overlapping", "unrelated", "mixed"}


def _validate_comparison(reply: dict | None) -> str | None:
    """Return an error message describing what is wrong, or None if valid."""
    if not isinstance(reply, dict):
        return "not a JSON object"
    if not isinstance(reply.get("comparison"), str) or not reply["comparison"].strip():
        return "missing 'comparison' text"
    score = reply.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
        return "'score' must be an integer between 1 and 10"
    just = reply.get("justifications")
    if (
        not isinstance(just, list)
        or not just
        or not all(isinstance(j, str) and j.strip() for j in just)
    ):
        return "'justifications' must be a non-empty list of strings"
    if reply.get("relationship") not in VALID_RELATIONSHIPS:
        return "'relationship' must be one of: complementary, overlapping, unrelated, mixed"
    return None


def run_comparison(client: Groq, startup_summary: str) -> dict:
    """One focused call: compare the startup to the DISW portfolio and score it.

    The reply is validated in code; on failure the validation error is fed
    back to the model for one retry.
    """
    messages = [
        {"role": "system", "content": COMPARE_SYSTEM},
        {"role": "user", "content": compare_user_msg(startup_summary, SIEMENS_DISW_CONTEXT)},
    ]
    error = "no attempt"
    for _ in range(2):
        reply, raw = _chat_json(client, messages)
        if isinstance(reply, dict):
            score = reply.get("score")
            if isinstance(score, float) and score.is_integer():
                reply["score"] = int(score)
            elif isinstance(score, str) and score.strip().isdigit():
                reply["score"] = int(score.strip())
        error = _validate_comparison(reply)
        if error is None:
            return reply
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": f"Invalid response ({error}). Return the corrected JSON object only."}
        )
    raise RuntimeError(f"Comparison failed validation twice ({error}).")

import requests
import streamlit as st
from openai import APIError, RateLimitError

from agent import (
    get_client,
    normalize_url,
    run_comparison,
    run_partner_similarity,
    run_research_agent,
)
from siemens_context import SOURCES

st.set_page_config(page_title="Startup Partner Fit Analyzer", page_icon="🤝")

st.title("🤝 Startup Partner Fit Analyzer")
st.caption(
    "Enter a startup's website URL. An LLM agent reads its public pages, "
    "summarizes the product offering, and ranks the startup's fit as a "
    "Siemens Digital Industries Software technology partner."
)


@st.cache_data(show_spinner=False)
def analyze(url: str) -> dict:
    """Run the full analysis for one URL.

    Cached on the URL: re-running the same startup returns instantly and costs
    no API tokens, which matters on the Groq free tier's daily budget.
    """
    client = get_client()
    if client is None:
        raise RuntimeError(
            "No Groq API key found. Add GROQ_API_KEY to .streamlit/secrets.toml "
            "(locally) or to the app's Secrets settings (on Streamlit Cloud)."
        )
    events: list[str] = []
    research = run_research_agent(client, url, on_event=events.append)
    return {
        "events": events,
        "summary": research["summary"],
        "pages_read": research["pages_read"],
        "comparison": run_comparison(client, research["summary"]),
        "partners": run_partner_similarity(client, research["summary"]),
    }


def _badge(score: int) -> str:
    return "🟢" if score >= 7 else ("🟡" if score >= 4 else "🔴")


url = st.text_input("Startup website URL", placeholder="https://www.manukai.ch/")

if st.button("Analyze", type="primary", disabled=not url):
    try:
        with st.status("Agent is analyzing the startup...", expanded=True) as status:
            data = analyze(normalize_url(url))
            for event in data["events"]:
                st.write(event)
            st.write("Compared against the Siemens DISW portfolio and partner list")
            status.update(
                label=f"Analysis complete — {len(data['pages_read'])} pages read",
                state="complete",
            )
    except (requests.RequestException, ValueError) as exc:
        st.error(
            f"Could not fetch the site: {exc}\n\n"
            "Check the URL, or the site may block automated access."
        )
        st.stop()
    except RateLimitError as exc:
        # The free tier has a daily token budget; say so plainly instead of
        # letting the provider's exception crash the page with a traceback.
        st.warning(
            "The LLM provider's free-tier rate limit was reached. "
            "Nothing is broken — the quota refills over a rolling window, so "
            "wait a few minutes and try again. Previously analyzed startups "
            "are cached and still work.",
            icon="⏳",
        )
        st.caption(f"Provider detail: {exc}")
        st.stop()
    except APIError as exc:
        st.error(f"The LLM provider returned an error: {exc}")
        st.stop()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    comparison, partners = data["comparison"], data["partners"]
    fit, similarity = comparison["score"], partners["similarity_score"]

    col_fit, col_sim, col_rel = st.columns([1, 1, 2])
    col_fit.metric("Partner fit", f"{fit}/10")
    col_sim.metric("Similarity to partners", f"{similarity}/10")
    col_rel.markdown(
        f"### {_badge(fit)} {comparison['relationship'].capitalize()}\n"
        "relative to the Siemens DISW portfolio"
    )

    st.subheader("Product summary")
    st.write(data["summary"])

    st.subheader("Comparison to Siemens DISW")
    st.write(comparison["comparison"])

    st.subheader("Why this score")
    for justification in comparison["justifications"]:
        st.markdown(f"- {justification}")

    st.subheader("Similarity to existing Siemens partners")
    st.markdown(f"**Closest partners:** {', '.join(partners['closest_partners'])}")
    st.write(partners["similarity_comparison"])
    for justification in partners["similarity_justifications"]:
        st.markdown(f"- {justification}")

    with st.expander("Pages the agent read"):
        for page in data["pages_read"]:
            st.markdown(f"- {page}")
    with st.expander("Siemens sources used"):
        st.caption("Siemens portfolio and partner list curated from these public pages.")
        for source in SOURCES:
            st.markdown(f"- {source}")

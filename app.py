import requests
import streamlit as st

from agent import get_client, run_comparison, run_research_agent

st.set_page_config(page_title="Startup Partner Fit Analyzer", page_icon="🤝")

st.title("🤝 Startup Partner Fit Analyzer")
st.caption(
    "Enter a startup's website URL. An LLM agent reads its public pages, "
    "summarizes the product offering, and ranks the startup's fit as a "
    "Siemens Digital Industries Software technology partner."
)

url = st.text_input("Startup website URL", placeholder="https://www.manukai.ch/")

if st.button("Analyze", type="primary", disabled=not url):
    client = get_client()
    if client is None:
        st.error(
            "No Groq API key found. Paste it into `.streamlit/secrets.toml` "
            'as `GROQ_API_KEY = "..."` and rerun.'
        )
        st.stop()

    try:
        with st.status("Agent is researching the startup...", expanded=True) as status:
            result = run_research_agent(client, url, on_event=st.write)
            status.update(
                label=f"Research complete — {len(result['pages_read'])} pages read",
                state="complete",
            )
        with st.status("Comparing against the Siemens DISW portfolio...") as status:
            comparison = run_comparison(client, result["summary"])
            status.update(label="Comparison complete", state="complete")
    except (requests.RequestException, ValueError) as exc:
        st.error(
            f"Could not fetch the site: {exc}\n\n"
            "Check the URL, or the site may block automated access."
        )
        st.stop()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    score = comparison["score"]
    badge = "🟢" if score >= 7 else ("🟡" if score >= 4 else "🔴")
    col_score, col_relation = st.columns([1, 2])
    col_score.metric("Partner fit", f"{score}/10")
    col_relation.markdown(
        f"### {badge} {comparison['relationship'].capitalize()}\n"
        "relative to the Siemens DISW portfolio"
    )

    st.subheader("Product summary")
    st.write(result["summary"])

    st.subheader("Comparison to Siemens DISW")
    st.write(comparison["comparison"])

    st.subheader("Why this score")
    for justification in comparison["justifications"]:
        st.markdown(f"- {justification}")

    with st.expander("Pages the agent read"):
        for page in result["pages_read"]:
            st.markdown(f"- {page}")

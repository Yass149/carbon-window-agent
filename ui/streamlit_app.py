"""Local chat, run-trace and human plan-approval interface."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx
import streamlit as st

DEFAULT_API = os.getenv("CWA_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = httpx.Timeout(5.0, connect=2.0)

st.set_page_config(
    page_title="Carbon Window Agent",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
      .stApp { background: linear-gradient(160deg, #f3f8f4 0%, #f8fafc 48%, #edf5f4 100%); }
      [data-testid="stHeader"] { background: rgba(243,248,244,.84); }
      .hero { padding: 1.3rem 1.5rem; border-radius: 18px; color: #effaf3;
              background: linear-gradient(115deg,#123d32,#1c6652 70%,#2b7662);
              margin: .5rem 0 1.2rem 0; box-shadow: 0 8px 28px #174a3922; }
      .hero h1 { margin: 0 0 .3rem 0; font-size: 2rem; }
      .hero p { margin: 0; color: #d7efe2; }
      [data-testid="stMetric"] { background: white; border: 1px solid #e1e9e4;
                                  padding: .8rem; border-radius: 14px; }
      .stButton button, .stFormSubmitButton button { border-radius: 10px; }
    </style>
    <div class="hero"><h1>🌿 Carbon Window Agent</h1>
    <p>Choose a cleaner time to use electricity, with every number traceable.</p></div>
    """,
    unsafe_allow_html=True,
)

if "cwa_session_id" not in st.session_state:
    st.session_state.cwa_session_id = uuid4().hex
if "cwa_chat" not in st.session_state:
    st.session_state.cwa_chat = []
if "cwa_last_run" not in st.session_state:
    st.session_state.cwa_last_run = None


def api_get(base: str, path: str) -> Any:
    """Return decoded JSON or raise a short, user-safe API error."""
    response = httpx.get(f"{base}{path}", timeout=TIMEOUT)
    if response.is_error:
        detail = response.json().get("error", {}).get("message", "The API request failed.")
        raise RuntimeError(detail)
    return response.json()


def api_post(base: str, path: str, body: dict[str, Any]) -> Any:
    """Post one action and return decoded JSON without hiding API errors."""
    response = httpx.post(f"{base}{path}", json=body, timeout=TIMEOUT)
    if response.is_error:
        detail = response.json().get("error", {}).get("message", "The API request failed.")
        raise RuntimeError(detail)
    return response.json()


with st.sidebar:
    st.subheader("Connection")
    api_base = st.text_input("API address", value=DEFAULT_API).strip().rstrip("/")
    try:
        health = api_get(api_base, "/health")
        st.success(f"Connected · {health['provider']} · {health['model']}")
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        st.error(f"API unavailable: {exc}")
        st.caption("Start the API in another terminal with `make run`.")
    st.caption("This local interface uses the provider configured for the API.")
    st.caption(f"Session: `{st.session_state.cwa_session_id[:12]}`")

chat_tab, plans_tab, about_tab = st.tabs(["Chat", "Plans", "About"])

with chat_tab:
    st.markdown("Ask about grid intensity, flexible loads, emissions or a heating plan.")
    for item in st.session_state.cwa_chat:
        with st.chat_message(item["role"]):
            if item["role"] == "assistant" and item.get("answer"):
                payload = item["answer"]
                st.markdown(payload.get("answer", ""))
                if payload.get("recommendation"):
                    st.success(payload["recommendation"])
                used = payload.get("numbers_used", [])
                if used:
                    columns = st.columns(min(len(used), 3))
                    for index, number in enumerate(used):
                        columns[index % len(columns)].metric(number["unit"], f"{number['value']:g}")
                if payload.get("assumptions"):
                    with st.expander("Assumptions and caveats"):
                        for text in payload["assumptions"]:
                            st.write(f"Assumption: {text}")
                        for text in payload.get("caveats", []):
                            st.write(f"Caveat: {text}")
                if payload.get("plan_id"):
                    st.info(f"Plan `{payload['plan_id']}` is pending. Review it in Plans.")
                if item.get("run_id"):
                    with st.expander("View run trace"):
                        try:
                            trace = api_get(api_base, f"/runs/{item['run_id']}")
                            for step in trace.get("trace", []):
                                label = f"{step['idx'] + 1}. {step['kind']}: {step['name']}"
                                st.markdown(f"**{label}**")
                                st.json(step)
                        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                            st.warning(f"Trace unavailable: {exc}")
            else:
                st.markdown(item["content"])

    question = st.chat_input("e.g. When should I charge my EV in RG1 tonight for 4 hours?")
    if question:
        st.session_state.cwa_chat.append({"role": "user", "content": question})
        with st.chat_message("assistant"):
            try:
                result = api_post(
                    api_base,
                    "/ask",
                    {"question": question, "session_id": st.session_state.cwa_session_id},
                )
                st.session_state.cwa_last_run = result.get("run_id")
                st.session_state.cwa_chat.append(
                    {"role": "assistant", "answer": result["answer"], "run_id": result["run_id"]}
                )
                st.rerun()
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
                st.error(f"Could not get an answer: {exc}")

with plans_tab:
    st.subheader("Human approval")
    st.caption("Saving a plan never starts a device. Approve or reject each plan here.")
    try:
        plans = api_get(api_base, "/plans")
        if not plans:
            st.info("There are no saved plans yet.")
        for plan in plans:
            with st.container(border=True):
                status = plan["status"].upper()
                st.markdown(f"**{plan['title']}** · {plan['device']} · `{status}`")
                st.write(f"From {plan['start']} to {plan['end']}")
                st.write(f"Expected emissions: {plan['expected_kg_co2']:g} kg CO2")
                if plan.get("notes"):
                    st.caption(plan["notes"])
                if plan["status"] == "pending":
                    approve_col, reject_col, spacer = st.columns([1, 1, 4])
                    if approve_col.button("Approve", key=f"approve-{plan['id']}"):
                        try:
                            api_post(api_base, f"/plans/{plan['id']}/approve", {})
                            st.success("Plan approved.")
                            st.rerun()
                        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                            st.error(f"Could not approve plan: {exc}")
                    if reject_col.button("Reject", key=f"reject-{plan['id']}"):
                        try:
                            api_post(api_base, f"/plans/{plan['id']}/reject", {})
                            st.info("Plan rejected.")
                            st.rerun()
                        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                            st.error(f"Could not reject plan: {exc}")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        st.error(f"Could not load plans: {exc}")

with about_tab:
    st.subheader("How answers are built")
    st.write(
        "Public carbon, postcode and weather data flows through typed tools. "
        "Scheduling arithmetic runs in tested Python. Every model tool call is "
        "recorded in the run trace, and saved plans stay pending until a person "
        "approves them."
    )
    st.info(
        "The default demo provider uses rules and no model tokens. The optional "
        "Anthropic provider can incur API charges when explicitly enabled."
    )

"""Local carbon-aware assistant, plan review and run-trace interface."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx
import streamlit as st

DEFAULT_API = os.getenv("CWA_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = httpx.Timeout(5.0, connect=2.0)
SUGGESTIONS = (
    "When should I charge my EV in RG1 tonight for 4 hours?",
    "Find a low-carbon window to run my washing machine tomorrow",
    "What is the carbon intensity in Reading right now?",
)

st.set_page_config(
    page_title="Carbon Window Agent",
    page_icon=":material/eco:",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "cwa_session_id" not in st.session_state:
    st.session_state.cwa_session_id = uuid4().hex
if "cwa_chat" not in st.session_state:
    st.session_state.cwa_chat = []
if "cwa_page" not in st.session_state:
    st.session_state.cwa_page = "Assistant"
if "cwa_prompt" not in st.session_state:
    st.session_state.cwa_prompt = ""


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
    st.markdown("## :material/eco: Carbon Window")
    st.caption("Carbon-aware energy planning")
    st.space("small")
    st.session_state.cwa_page = st.radio(
        "Workspace",
        ("Assistant", "Plans", "About"),
        key="cwa_navigation",
        label_visibility="collapsed",
        format_func=lambda page: {
            "Assistant": "Assistant",
            "Plans": "Plan review",
            "About": "How it works",
        }[page],
    )
    st.space("large")
    st.subheader("Connection")
    api_base = st.text_input("API address", value=DEFAULT_API).strip().rstrip("/")
    try:
        health = api_get(api_base, "/health")
        st.success(
            f"Online · {health['provider']} / {health['model']}",
            icon=":material/check_circle:",
        )
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        st.error(f"API unavailable: {exc}", icon=":material/cloud_off:")
        st.caption("Start the API in another terminal with `make run`.")
    st.caption("The local demo uses no model tokens.")
    st.caption(f"Session `{st.session_state.cwa_session_id[:12]}`")


def show_trace(run_id: str, api_base: str) -> None:
    """Load and display the recorded steps for one answer on demand."""
    try:
        trace = api_get(api_base, f"/runs/{run_id}")
        steps = trace.get("trace", [])
        if not steps:
            st.caption("No trace steps were recorded for this run.")
        for step in steps:
            title = f"{step['idx'] + 1:02d} · {step['kind']} · {step['name']}"
            with st.expander(title):
                st.json(step)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        st.warning(f"Trace unavailable: {exc}")


def show_answer(item: dict[str, Any], api_base: str) -> None:
    """Render a structured answer with its caveats and trace details."""
    payload = item["answer"]
    st.markdown(payload.get("answer", ""))
    if payload.get("recommendation"):
        st.success(payload["recommendation"], icon=":material/schedule:")
    numbers = payload.get("numbers_used", [])
    if numbers:
        metric_columns = st.columns(min(len(numbers), 4))
        for index, number in enumerate(numbers):
            metric_columns[index % len(metric_columns)].metric(
                number.get("unit", "Value"), f"{number['value']:g}"
            )
    if payload.get("assumptions") or payload.get("caveats"):
        with st.expander("Assumptions and caveats", icon=":material/info:"):
            for text in payload.get("assumptions", []):
                st.markdown(f"- Assumption: {text}")
            for text in payload.get("caveats", []):
                st.markdown(f"- Caveat: {text}")
    if payload.get("plan_id"):
        st.info(f"Plan `{payload['plan_id']}` is ready for review in Plan review.")
    if item.get("run_id"):
        if st.toggle(
            "View run trace",
            key=f"trace-{item['run_id']}",
            help="Load the recorded model and data-tool steps for this answer.",
        ):
            show_trace(item["run_id"], api_base)


def submit_question(question: str, api_base: str) -> None:
    """Send a question to the API and persist both sides of the exchange."""
    clean_question = question.strip()
    if not clean_question:
        return
    st.session_state.cwa_chat.append({"role": "user", "content": clean_question})
    try:
        result = api_post(
            api_base,
            "/ask",
            {"question": clean_question, "session_id": st.session_state.cwa_session_id},
        )
        st.session_state.cwa_chat.append(
            {"role": "assistant", "answer": result["answer"], "run_id": result["run_id"]}
        )
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        st.session_state.cwa_chat.append({"role": "error", "content": str(exc)})


if st.session_state.cwa_page == "Assistant":
    st.title("Carbon Window Agent", anchor=False)
    st.markdown(
        "Plan flexible energy use for cleaner hours. **Every recommendation is traceable.**"
    )
    st.space("small")

    if not st.session_state.cwa_chat:
        with st.container(border=True):
            st.subheader("Find a cleaner time to use energy", anchor=False)
            st.write(
                "Ask about EV charging, household devices, grid intensity or a flexible "
                "schedule. Your plan stays under your control."
            )
            st.caption("Try a question")
            with st.container(horizontal=True):
                for index, prompt in enumerate(SUGGESTIONS):
                    if st.button(
                        ("EV charging", "Laundry", "Grid intensity")[index],
                        key=f"suggestion-{index}",
                        icon=(
                            ":material/ev_station:",
                            ":material/local_laundry_service:",
                            ":material/bolt:",
                        )[index],
                        help=prompt,
                    ):
                        st.session_state.cwa_prompt = prompt
                        st.rerun()

    for item in st.session_state.cwa_chat:
        if item["role"] == "error":
            st.error(f"Could not get an answer: {item['content']}")
            continue
        with st.chat_message(item["role"]):
            if item["role"] == "assistant":
                show_answer(item, api_base)
            else:
                st.markdown(item["content"])

    question = st.chat_input(
        "Ask about a device, place or time window...",
        key="assistant-question",
    )
    if st.session_state.cwa_prompt:
        question = st.session_state.cwa_prompt
        st.session_state.cwa_prompt = ""
    if question:
        submit_question(question, api_base)
        st.rerun()

elif st.session_state.cwa_page == "Plans":
    st.title("Plan review", anchor=False)
    st.markdown("Review recommendations before you act on them.")
    st.info(
        "Saving a plan never starts a device. Each plan needs your approval.",
        icon=":material/verified_user:",
    )
    try:
        plans = api_get(api_base, "/plans")
        if not plans:
            with st.container(border=True):
                st.subheader("No plans yet", anchor=False)
                st.write("Ask the assistant to find a cleaner window for a flexible device.")
        for plan in plans:
            with st.container(border=True):
                status = plan["status"].lower()
                badge_color = (
                    "orange" if status == "pending" else "green" if status == "approved" else "gray"
                )
                st.badge(status.capitalize(), color=badge_color)
                st.subheader(plan["title"], anchor=False)
                st.caption(plan["device"])
                details = st.columns(3)
                details[0].markdown("**Start**")
                details[0].write(plan["start"])
                details[1].markdown("**End**")
                details[1].write(plan["end"])
                details[2].markdown("**Estimated emissions**")
                details[2].write(f"{plan['expected_kg_co2']:g} kg CO₂")
                if plan.get("notes"):
                    st.caption(plan["notes"])
                if status == "pending":
                    with st.container(horizontal=True):
                        if st.button(
                            "Approve plan",
                            key=f"approve-{plan['id']}",
                            type="primary",
                            icon=":material/check:",
                        ):
                            try:
                                api_post(api_base, f"/plans/{plan['id']}/approve", {})
                                st.toast("Plan approved")
                                st.rerun()
                            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                                st.error(f"Could not approve plan: {exc}")
                        if st.button("Reject", key=f"reject-{plan['id']}", icon=":material/close:"):
                            try:
                                api_post(api_base, f"/plans/{plan['id']}/reject", {})
                                st.toast("Plan rejected")
                                st.rerun()
                            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                                st.error(f"Could not reject plan: {exc}")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        st.error(f"Could not load plans: {exc}")

else:
    st.title("How it works", anchor=False)
    st.markdown("### Evidence first. Your decision always.")
    st.write(
        "The assistant combines public carbon, postcode and weather data with tested "
        "scheduling arithmetic. Each answer shows the data and tool calls behind it, "
        "so you can inspect how a recommendation was made."
    )
    with st.container(border=True):
        st.subheader("Your energy plan stays in your hands", anchor=False)
        st.write(
            "Recommendations can be saved for review. Devices are never controlled "
            "automatically, and a saved plan remains pending until you approve it."
        )
    with st.container(border=True):
        st.subheader("Private by default, free to try", anchor=False)
        st.write(
            "The default local demo uses a rules-based provider and no model tokens. "
            "An optional Anthropic provider can be configured for the API and may incur charges."
        )
        st.caption("The app connects to the API address shown in the sidebar.")

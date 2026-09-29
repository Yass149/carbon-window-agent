"""Local carbon-aware scheduling app with guided planning and transparent results."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st

from cwa.tools.scheduling import estimate_emissions

DEFAULT_API = os.getenv("CWA_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = httpx.Timeout(5.0, connect=2.0)
LONDON = ZoneInfo("Europe/London")
SUGGESTIONS = (
    "When is the cleanest 4-hour window to charge my EV in RG1 tonight?",
    "What is the current carbon intensity in RG1?",
    "Estimate emissions for a 2 kWh load in RG1 right now.",
)
WINDOWS = {
    "Tonight (20:00–07:00)": "tonight between 20:00 and 07:00",
    "Tomorrow morning (00:00–12:00)": "tomorrow between 00:00 and 12:00",
    "Next 24 hours": "over the next 24 hours",
}
DEVICES = ("EV charging", "Dishwasher", "Heat pump", "Other flexible load")

st.set_page_config(
    page_title="Carbon Window Agent",
    page_icon=":material/eco:",
    layout="wide",
    initial_sidebar_state="expanded",
)

for key, value in {
    "cwa_session_id": uuid4().hex,
    "cwa_chat": [],
    "cwa_page": "Plan a run",
    "cwa_prompt": "",
    "cwa_traces": {},
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def api_get(base: str, path: str) -> Any:
    """Return decoded JSON or raise a short, user-safe API error."""
    response = httpx.get(f"{base}{path}", timeout=TIMEOUT)
    if response.is_error:
        try:
            detail = response.json().get("error", {}).get("message", "The API request failed.")
        except (ValueError, TypeError):
            detail = "The API request failed."
        raise RuntimeError(detail)
    return response.json()


def api_post(base: str, path: str, body: dict[str, Any]) -> Any:
    """Post one action and return decoded JSON without hiding API errors."""
    response = httpx.post(f"{base}{path}", json=body, timeout=TIMEOUT)
    if response.is_error:
        try:
            detail = response.json().get("error", {}).get("message", "The API request failed.")
        except (ValueError, TypeError):
            detail = "The API request failed."
        raise RuntimeError(detail)
    return response.json()


@st.cache_data(ttl=15, show_spinner=False)
def api_health(base: str) -> dict[str, Any]:
    """Read non-sensitive health metadata briefly cached for the sidebar."""
    return api_get(base, "/health")


def read_trace(run_id: str, api_base: str) -> dict[str, Any]:
    """Load one trace once per browser session so answer reruns stay quick."""
    traces = st.session_state.cwa_traces
    if run_id not in traces:
        traces[run_id] = api_get(api_base, f"/runs/{run_id}")
    return traces[run_id]


def local_time(value: str, format_string: str = "%a %d %b · %H:%M %Z") -> str:
    """Format an aware timestamp in the GB grid's local timezone."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(LONDON).strftime(
        format_string
    )


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


def schedule_question(
    place: str, device: str, hours: int, window: str, energy_kwh: float, save: bool
) -> str:
    """Build direct wording understood by both the free rules demo and Claude."""
    question = (
        f"Find the lowest-carbon window for {device} in {place.strip()} {window}. "
        f"Run continuously for {hours} hours."
    )
    if energy_kwh > 0:
        question += f" Expected energy use: {energy_kwh:g} kWh."
    if save:
        question += " Save a plan for this run."
    return question


def tool_result(trace: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    """Find the successful result of a named tool in one recorded run."""
    for step in trace.get("trace", []):
        if step.get("kind") == "tool" and step.get("name") == tool_name and not step.get(
            "is_error", False
        ):
            output = step.get("output")
            if isinstance(output, dict):
                return output
    return None


def show_schedule_comparison(forecast: dict[str, Any], window: dict[str, Any]) -> None:
    """Show the forecast curve and highlight the scheduler's selected interval."""
    slots = forecast.get("slots", [])
    if not slots:
        return
    best_start = pd.to_datetime(window["start"], utc=True)
    best_end = pd.to_datetime(window["end"], utc=True)
    rows = []
    for slot in slots:
        slot_start = pd.to_datetime(slot["from_time"], utc=True)
        slot_end = pd.to_datetime(slot["to_time"], utc=True)
        intensity = slot["intensity_gco2_kwh"]
        chosen = slot_end > best_start and slot_start < best_end
        rows.append(
            {
                "Time": slot_start.tz_convert(LONDON),
                "Forecast intensity": intensity,
                "Recommended window": intensity if chosen else None,
            }
        )
    chart = pd.DataFrame(rows)

    with st.container(border=True):
        st.subheader("Why this time?", anchor=False)
        st.caption(
            "The shaded line marks the selected run. The scheduler chooses the lowest "
            "average forecast intensity that fits your duration and available window."
        )
        st.line_chart(
            chart,
            x="Time",
            y=["Forecast intensity", "Recommended window"],
            y_label="gCO₂ per kWh",
            color=["#B3C2BB", "#16745B"],
            height=260,
        )
        baseline = window.get("now_avg_intensity")
        average = window.get("avg_intensity")
        saving = window.get("saving_percent")
        metrics = st.columns(3)
        metrics[0].metric("Recommended average", f"{average:.1f} gCO₂/kWh")
        if baseline is not None:
            metrics[1].metric("Earliest-start baseline", f"{baseline:.1f} gCO₂/kWh")
        if saving is not None:
            metrics[2].metric(
                "Lower than baseline",
                f"{saving:.1f}%",
                help="Compared with the same duration starting at the earliest time you allowed.",
            )
        scope = forecast.get("scope", "regional")
        region = forecast.get("region_name", "your selected region")
        retrieved = forecast.get("retrieved_at")
        when = f" · Retrieved {local_time(retrieved, '%d %b %Y, %H:%M %Z')}" if retrieved else ""
        st.caption(f"{region} · {scope.title()} forecast{when}. Forecast values can change.")
        st.write(
            "Grid intensity changes as demand and the generation mix change. This is a "
            "comparison of average forecast CO₂ per kWh, not an electricity-price or "
            "marginal-emissions calculation."
        )


def show_trace(run_id: str, api_base: str) -> None:
    """Load and display the recorded steps for one answer on demand."""
    try:
        trace = read_trace(run_id, api_base)
        steps = trace.get("trace", [])
        if not steps:
            st.caption("No trace steps were recorded for this run.")
        for step in steps:
            title = f"{step['idx'] + 1:02d} · {step['kind']} · {step['name']}"
            with st.expander(title):
                st.json(step)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        st.warning(f"Trace unavailable: {exc}")


def show_suggestions(api_base: str, key_suffix: str) -> None:
    """Offer known-good question examples after an empty state or refusal."""
    with st.container(horizontal=True):
        labels = ("Plan EV charging", "Check regional intensity", "Estimate load emissions")
        for index, prompt in enumerate(SUGGESTIONS):
            if st.button(labels[index], key=f"suggest-{key_suffix}-{index}"):
                with st.spinner("Checking the carbon forecast…"):
                    submit_question(prompt, api_base)
                st.rerun()


def show_answer(item: dict[str, Any], api_base: str) -> None:
    """Render an evidence-led answer, schedule comparison and optional audit trace."""
    payload = item["answer"]
    st.markdown(payload.get("answer", ""))
    if payload.get("recommendation"):
        st.success(payload["recommendation"], icon=":material/schedule:")

    schedule_data = None
    run_id = item.get("run_id")
    if run_id and any(
        number.get("unit") == "gCO2/kWh" for number in payload.get("numbers_used", [])
    ):
        try:
            trace = read_trace(run_id, api_base)
            forecast = tool_result(trace, "get_carbon_forecast")
            window = tool_result(trace, "find_lowest_carbon_window")
            if forecast and window:
                schedule_data = forecast, window
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError):
            st.caption("Forecast timeline is unavailable for this run.")

    numbers = payload.get("numbers_used", [])
    if numbers:
        visible_numbers = [
            number
            for number in numbers
            if not (schedule_data and number.get("unit") in {"gCO2/kWh", "%"})
        ]
        metric_columns = st.columns(min(len(visible_numbers), 3)) if visible_numbers else []
        for index, number in enumerate(visible_numbers):
            unit = number.get("unit", "")
            value = number["value"]
            if unit == "gCO2/kWh":
                label, formatted = "Forecast intensity", f"{value:.1f} gCO₂/kWh"
            elif unit == "%":
                label, formatted = "Lower than earliest start", f"{value:.1f}%"
            elif unit in {"kg CO2", "kg CO₂"}:
                label, formatted = "Estimated load emissions", f"{value:.3f} kg CO₂"
            elif unit == "kWh":
                label, formatted = "Energy use", f"{value:g} kWh"
            else:
                label, formatted = unit or "Measured value", f"{value:g} {unit}".strip()
            metric_columns[index % len(metric_columns)].metric(label, formatted)

    if schedule_data:
        show_schedule_comparison(*schedule_data)

    if payload.get("assumptions") or payload.get("caveats"):
        with st.expander("Assumptions and forecast limits", icon=":material/info:"):
            for text in payload.get("assumptions", []):
                st.markdown(f"- {text}")
            for text in payload.get("caveats", []):
                st.markdown(f"- {text}")
    if payload.get("plan_id"):
        st.info(
            f"Plan `{payload['plan_id']}` is pending. Review and approve it in Plan review; "
            "approval does not control a device."
        )
    if run_id and st.toggle(
        "Show technical run trace",
        key=f"trace-toggle-{run_id}",
        help="Inspect the model and data-tool records used to build this answer.",
    ):
        show_trace(run_id, api_base)

    if payload.get("needs_clarification"):
        st.caption("Include a GB postcode or outcode, device duration and available time window.")
    if not numbers and not payload.get("recommendation") and not payload.get("plan_id"):
        st.caption("Try a supported example")
        show_suggestions(api_base, item.get("run_id", uuid4().hex))


def render_history(api_base: str) -> None:
    """Render the current browser session's conversation."""
    for item in st.session_state.cwa_chat:
        if item["role"] == "error":
            st.error(f"Could not get an answer: {item['content']}")
            continue
        with st.chat_message(item["role"]):
            if item["role"] == "assistant":
                show_answer(item, api_base)
            else:
                st.markdown(item["content"])


def schedule_page(api_base: str) -> None:
    """Guide people through a fully specified flexible-load question."""
    st.title("Find a cleaner time to run a device", anchor=False)
    st.markdown(
        "Use a time window that already works for you. Compare the carbon forecast "
        "before deciding whether to shift the run."
    )
    value_cards = st.columns(2)
    with value_cards[0].container(border=True):
        st.markdown("**Same task. Different grid hour.**")
        st.write(
            "Grid CO₂ per kWh changes through the day. If a device can wait, compare "
            "the estimated electricity footprint for different run times."
        )
    with value_cards[1].container(border=True):
        st.markdown("**Use it when it fits your priorities.**")
        st.write(
            "This tool estimates carbon, not cost. It will not control a device or "
            "change your tariff; convenience always comes first."
        )
    with st.container(border=True):
        st.subheader("Plan a flexible run", anchor=False)
        st.caption(
            "The form builds a complete question for you. It does not start or schedule a device."
        )
        with st.form("schedule-form", border=False):
            left, right = st.columns(2)
            place = left.text_input("GB postcode or outcode", value="RG1", max_chars=8)
            device = right.selectbox("What do you want to run?", DEVICES)
            duration = left.selectbox("How long does it need to run?", (1, 2, 3, 4, 6, 8), index=3)
            window_label = right.selectbox("When could it run?", tuple(WINDOWS))
            energy = left.number_input(
                "Energy use (optional, kWh)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.5,
                help="Enter kWh for an estimated load footprint. Leave at 0 to skip it.",
            )
            save = right.checkbox(
                "Save this as a pending plan",
                help="A saved plan waits for a human to approve it; no device is controlled.",
            )
            submitted = st.form_submit_button(
                "Compare forecast windows",
                type="primary",
                icon=":material/search:",
                width="stretch",
            )
        if submitted:
            if not place.strip():
                st.error("Enter a GB postcode or outcode to look up the regional forecast.")
            elif save and energy <= 0:
                st.error("Enter the load's energy use in kWh before saving a plan.")
            else:
                question = schedule_question(
                    place, device, duration, WINDOWS[window_label], energy, save
                )
                with st.spinner("Comparing the available carbon forecast windows…"):
                    submit_question(question, api_base)
                st.rerun()

    st.caption(
        "Intensity is not a tariff. Use this comparison when the run is flexible; "
        "if price or convenience matters more, keep your existing schedule."
    )
    render_history(api_base)


def conversation_page(api_base: str) -> None:
    """Offer free-text follow-ups and known-supported examples."""
    st.title("Ask about electricity and carbon", anchor=False)
    st.markdown(
        "Ask about regional intensity, a flexible run or estimated load emissions. "
        "The default free assistant works best with short, direct questions."
    )
    if not st.session_state.cwa_chat:
        st.caption("Try one of these")
        show_suggestions(api_base, "conversation")
    render_history(api_base)
    question = st.chat_input("Ask about a GB postcode, flexible load or time window…")
    if st.session_state.cwa_prompt:
        question = st.session_state.cwa_prompt
        st.session_state.cwa_prompt = ""
    if question:
        with st.spinner("Checking public grid data…"):
            submit_question(question, api_base)
        st.rerun()


def plans_page(api_base: str) -> None:
    """Display saved plans as an explicit human review queue."""
    st.title("Plan review", anchor=False)
    st.markdown("Your suggestions stay here until you approve or decline them.")
    st.info(
        "Approval records your decision only. The app never connects to or controls a device.",
        icon=":material/verified_user:",
    )
    try:
        plans = api_get(api_base, "/plans")
        pending = sum(plan["status"] == "pending" for plan in plans)
        approved = sum(plan["status"] == "approved" for plan in plans)
        rejected = sum(plan["status"] == "rejected" for plan in plans)
        with st.container(horizontal=True):
            st.metric("Needs review", pending, border=True)
            st.metric("Approved", approved, border=True)
            st.metric("Declined", rejected, border=True)
        if not plans:
            with st.container(border=True):
                st.subheader("No saved plans", anchor=False)
                st.write(
                    "Use Plan a run and select ‘Save this as a pending plan’ to create "
                    "a suggestion for review."
                )
        for plan in plans:
            with st.container(border=True):
                status = plan["status"].lower()
                color = (
                    "orange" if status == "pending" else "green" if status == "approved" else "gray"
                )
                st.badge(status.capitalize(), color=color)
                st.subheader(plan["title"], anchor=False)
                st.caption(plan["device"])
                details = st.columns(3)
                details[0].markdown("**Suggested start**")
                details[0].write(local_time(plan["start"]))
                details[1].markdown("**Suggested end**")
                details[1].write(local_time(plan["end"]))
                details[2].markdown("**Estimated load emissions**")
                details[2].write(f"{plan['expected_kg_co2']:.3f} kg CO₂")
                st.caption("Estimate assumes the energy use and constant-power run provided.")
                if plan.get("notes"):
                    st.caption(plan["notes"])
                if status == "pending":
                    with st.container(horizontal=True):
                        if st.button(
                            "Approve suggestion",
                            key=f"approve-{plan['id']}",
                            type="primary",
                            icon=":material/check:",
                        ):
                            try:
                                api_post(api_base, f"/plans/{plan['id']}/approve", {})
                                st.toast("Suggestion approved")
                                st.rerun()
                            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                                st.error(f"Could not approve the suggestion: {exc}")
                        if st.button(
                            "Decline",
                            key=f"reject-{plan['id']}",
                            icon=":material/close:",
                        ):
                            try:
                                api_post(api_base, f"/plans/{plan['id']}/reject", {})
                                st.toast("Suggestion declined")
                                st.rerun()
                            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                                st.error(f"Could not decline the suggestion: {exc}")
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        st.error(f"Could not load plans: {exc}")


def learn_page(api_base: str, health: dict[str, Any] | None) -> None:
    """Explain the product's value, calculation and boundaries in plain language."""
    st.title("Why timing can make a difference", anchor=False)
    st.markdown(
        "You do not need to change everything. This tool is for the electricity use "
        "you can move without disrupting your day."
    )
    st.markdown("### Why can the same device have a different footprint by hour?")
    st.write(
        "The grid's carbon intensity is the estimated CO₂ associated with each kWh "
        "consumed. It changes as electricity demand and the generation mix change. "
        "Weather affects wind and solar output; dispatchable generation and imports "
        "also vary. The system operator forecasts this changing average intensity in "
        "half-hour periods."
    )
    st.caption(
        "A lower-intensity interval means fewer forecast grams of CO₂ per kWh on the "
        "grid average. It does not prove which generator responds to one extra device."
    )
    st.markdown(
        "Source: [NESO Carbon Intensity API](https://www.carbonintensity.org.uk/) · "
        "[API documentation](https://api.carbonintensity.org.uk/)"
    )

    left, right = st.columns(2)
    with left.container(border=True):
        st.subheader("A simple example", anchor=False)
        st.write("For the same 5 kWh job:")
        at_100 = estimate_emissions(5, 100).kg_co2
        at_200 = estimate_emissions(5, 200).kg_co2
        st.metric("At 100 gCO₂/kWh", f"{at_100:.2f} kg CO₂")
        st.metric("At 200 gCO₂/kWh", f"{at_200:.2f} kg CO₂")
        st.caption(
            "Load emissions = kWh × average grid intensity ÷ 1,000. Illustrative example, "
            "not a live forecast. Same energy, different "
            "average grid intensity; real outcomes are estimates."
        )
    with right.container(border=True):
        st.subheader("Who may find it useful?", anchor=False)
        st.markdown(
            "- EV owners who can choose when to charge\n"
            "- Households with a flexible appliance cycle\n"
            "- Facilities teams reviewing flexible loads\n"
            "- Anyone curious about the carbon footprint of electricity use"
        )
        st.write(
            "It helps compare carbon forecasts and make a more informed schedule; "
            "it does not promise financial savings."
        )

    st.markdown("### How a recommendation is made")
    with st.container(horizontal=True):
        with st.container(border=True):
            st.markdown("**1 · Forecast**")
            st.write("Retrieve regional half-hour carbon-intensity estimates for your postcode.")
        with st.container(border=True):
            st.markdown("**2 · Compare**")
            st.write("Calculate the average intensity for every possible continuous run window.")
        with st.container(border=True):
            st.markdown("**3 · Explain**")
            st.write("Show the selected interval, earliest-start comparison and assumptions.")

    st.info(
        "If your priority is the cheapest electricity, follow your tariff: this app does "
        "not compare prices. If the task is urgent or shifting it is inconvenient, run it "
        "when you need to."
    )

    st.markdown("### What the estimate does—and does not—mean")
    st.markdown(
        "- The percentage compares the selected run with the same duration starting at "
        "the **earliest time in your chosen window**. It is not necessarily a comparison "
        "with charging now.\n"
        "- Estimated load emissions use `kWh × average grid intensity ÷ 1,000`. The result "
        "is a location-based estimate, not a guarantee of avoided or marginal emissions.\n"
        "- Forecasts can change and extend up to 48 hours. Regional data may fall back to "
        "a labelled GB-wide forecast.\n"
        "- The schedule assumes a continuous run at constant power. It does not know your "
        "vehicle battery, charger limits, device cycle, tariff or building heat demand.\n"
        "- The free provider follows narrow rules and does not understand general chat. "
        "Claude can be configured separately, but it uses a paid API."
    )
    if health and health.get("provider") == "demo":
        st.success("Current mode: free rules demo · zero model tokens")
    elif health:
        st.warning(
            f"Current mode: {health.get('provider')} / {health.get('model')} · "
            "API usage may be billed by the provider."
        )


with st.sidebar:
    st.markdown("## :material/eco: Carbon Window")
    st.caption("Flexible energy, informed by the grid")
    page = st.radio(
        "Workspace",
        ("Plan a run", "Conversation", "Plan review", "Why timing?"),
        key="cwa_navigation",
        label_visibility="collapsed",
    )
    st.space("small")
    api_base = DEFAULT_API
    with st.expander("Connection settings"):
        api_base = st.text_input("Local API address", value=DEFAULT_API).strip().rstrip("/")
        st.caption("Keep the API running while you use the app.")
        st.caption(f"Session reference: `{st.session_state.cwa_session_id[:12]}`")
    try:
        health = api_health(api_base)
        provider = health.get("provider")
        if provider == "demo":
            st.success("Free demo · no model charges", icon=":material/check_circle:")
        else:
            st.info(f"{provider} · provider API may be billed", icon=":material/bolt:")
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError):
        health = None
        st.error("API offline", icon=":material/cloud_off:")
        st.caption("Start the API with `make run` in another terminal.")


if page == "Plan a run":
    schedule_page(api_base)
elif page == "Conversation":
    conversation_page(api_base)
elif page == "Plan review":
    plans_page(api_base)
else:
    learn_page(api_base, health)

"""MRG Laboratories - Sample Intake Dashboard + Chatbot (Schneider Prize 2026 demo)."""
import json
import os
import pandas as pd
import requests
import streamlit as st

# _snowflake only exists in the warehouse runtime; the container runtime uses REST instead.
try:
    import _snowflake
except ImportError:
    _snowflake = None

DB_SCHEMA = "MRG_LABS_DB.INTAKE"
SEMANTIC_VIEW = f"{DB_SCHEMA}.MRG_INTAKE_SV"

# All UI strings live here so a language selector can be added later
# (add e.g. TEXT["es"] = {...} and a st.selectbox to choose LANG).
TEXT = {
    "en": {
        "title": "MRG Laboratories - Sample Intake",
        "upload": "Upload weekly OCR output CSV",
        "loaded": "Loaded {n} rows into batch {b}",
        "batch": "Batch",
        "samples": "Samples", "dups": "Duplicate IDs", "missing": "Missing fields",
        "bad_dates": "Bad dates", "turnaround": "Avg turnaround (days)",
        "tab_dash": "Dashboard", "tab_chat": "Ask the data", "tab_fix": "Flagged samples", "tab_data": "Data",
        "per_day": "Samples received per day", "per_machine": "Samples per machine",
        "per_component": "Samples per component", "per_tube": "Small vs Large tubes",
        "chat_hint": "Ask a question, e.g. 'Which machines have the longest turnaround?'",
        "dup_alert": "{n} rows share a Sample ID and are flagged - see the Flagged samples tab.",
        "no_issues": "No flagged samples - ready to submit.",
        "save": "Save flag changes", "saved": "Flag changes saved.",
        "unflag_col": "Unflag", "unflag_hint": "Tick 'Unflag' to clear a flag (untick to re-flag), then save.",
        "submit": "Submit to MRG",
        "blocked": "Resolve duplicate Sample IDs before submitting.",
        "submitted": "Your data has been submitted to MRG: {n} samples ({f} flagged for review).",
        "popup_title": "Submitted to MRG",
        "flag_note": "{n} samples are flagged. Labels can't be corrected - they will be submitted with their flag.",
        "nothing": "No pending samples in this batch.",
        "feed": "Server feed", "feed_mode": "Mode", "feed_source": "Source",
        "feed_last": "Last pull", "feed_new": "Rows imported (last pull)", "feed_total": "Server rows read so far",
        "feed_pull": "Pull from server now", "feed_sim": "Simulate new server rows",
        "feed_sim_n": "Rows to add", "feed_never": "Never", "feed_err": "Last pull failed: {e}",
        "feed_history": "Recent pulls",
    }
}
LANG = "en"
T = TEXT[LANG]

st.set_page_config(page_title="MRG Intake", layout="wide")
session = st.connection("snowflake").session()

CSV_COLS = ["SAMPLE_ID", "DATE_SAMPLED", "DATE_RECEIVED", "MACHINE", "COMPONENT",
            "SERIAL_NUMBER", "REFERENCE_LUBE"]


def q(sql: str, params=None) -> pd.DataFrame:
    return session.sql(sql, params=params).to_pandas()


st.title(T["title"])

# ---------- Server feed (PULL_FEED imports only rows it hasn't seen) ----------
with st.expander(T["feed"], expanded=True):
    cfg = q(f"SELECT MODE, SOURCE_URL, SIM_FILE FROM {DB_SCHEMA}.FEED_CONFIG").iloc[0]
    runs = q(f"SELECT * FROM {DB_SCHEMA}.FEED_RUN_LOG ORDER BY RUN_AT DESC LIMIT 10")
    state = q(f"SELECT LAST_ROW_NUMBER FROM {DB_SCHEMA}.FEED_STATE")
    src = cfg["SOURCE_URL"] if cfg["MODE"] == "LIVE" else f"@SIM_SERVER/{cfg['SIM_FILE']} (stand-in for {cfg['SOURCE_URL']})"
    k = st.columns(4)
    k[0].metric(T["feed_mode"], cfg["MODE"])
    k[1].metric(T["feed_last"], f"{runs.iloc[0]['RUN_AT']:%b %d %H:%M}" if len(runs) else T["feed_never"])
    k[2].metric(T["feed_new"], int(runs.iloc[0]["ROWS_NEW"]) if len(runs) else 0)
    k[3].metric(T["feed_total"], int(state.iloc[0, 0]) if len(state) else 0)
    st.caption(f"{T['feed_source']}: {src}")
    if len(runs) and pd.notna(runs.iloc[0]["ERROR"]):
        st.error(T["feed_err"].format(e=runs.iloc[0]["ERROR"]))
    b1, b2, b3 = st.columns([2, 2, 1])
    if b1.button(T["feed_pull"], type="primary", use_container_width=True):
        with st.spinner(T["feed_pull"]):
            msg = session.sql(f"CALL {DB_SCHEMA}.PULL_FEED()").collect()[0][0]
        st.session_state.feed_msg = msg
        st.rerun()
    if cfg["MODE"] == "SIMULATED":
        n_add = b3.number_input(T["feed_sim_n"], 1, 500, 50, label_visibility="collapsed")
        if b2.button(T["feed_sim"], use_container_width=True):
            st.toast(session.sql(f"CALL {DB_SCHEMA}.SIMULATE_SERVER_APPEND({int(n_add)})").collect()[0][0])
    if "feed_msg" in st.session_state:
        m = st.session_state.pop("feed_msg")
        (st.error if m.startswith("ERROR") else st.success)(m)
    if len(runs):
        st.caption(T["feed_history"])
        st.dataframe(runs[["RUN_AT", "ROWS_READ", "ROWS_NEW", "METHOD", "BATCH_ID", "ERROR"]],
                     hide_index=True, use_container_width=True)

# ---------- Upload ----------
with st.expander(T["upload"]):
    f = st.file_uploader("CSV", type="csv", label_visibility="collapsed")
    if f is not None and st.button("Load"):
        df = pd.read_csv(f, dtype=str)
        df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
        df = df.reindex(columns=CSV_COLS + (["TUBE_SIZE"] if "TUBE_SIZE" in df.columns else []))
        if "TUBE_SIZE" not in df.columns:
            df["TUBE_SIZE"] = None
        batch = f"BATCH_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
        df["BATCH_ID"] = batch
        session.write_pandas(df, "STAGING_SAMPLES", database="MRG_LABS_DB", schema="INTAKE",
                             auto_create_table=False, overwrite=False)
        session.sql(f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'PENDING' WHERE STATUS IS NULL").collect()
        st.success(T["loaded"].format(n=len(df), b=batch))

batches = q(f"SELECT DISTINCT BATCH_ID FROM {DB_SCHEMA}.STAGING_SAMPLES ORDER BY 1 DESC")["BATCH_ID"].tolist()
if not batches:
    st.info(T["nothing"])
    st.stop()
batch = st.selectbox(T["batch"], batches)

data = q(f"SELECT * FROM {DB_SCHEMA}.MRG_VIEW WHERE BATCH_ID = ?", [batch])
pending = data[data["STATUS"] == "PENDING"]
dup_rows = pending[pending["IS_DUPLICATE"]]

# ---------- KPIs ----------
c = st.columns(5)
c[0].metric(T["samples"], len(data))
c[1].metric(T["dups"], int(data["IS_DUPLICATE"].sum()))
c[2].metric(T["missing"], int(data["HAS_MISSING_FIELD"].sum()))
c[3].metric(T["bad_dates"], int(data["HAS_BAD_DATE"].sum()))
c[4].metric(T["turnaround"], round(float(data["TURNAROUND_DAYS"].mean() or 0), 1))

if len(dup_rows):
    st.warning(T["dup_alert"].format(n=len(dup_rows)))

tab_dash, tab_chat, tab_fix, tab_data = st.tabs([T["tab_dash"], T["tab_chat"], T["tab_fix"], T["tab_data"]])

# ---------- Dashboard ----------
with tab_dash:
    a, b = st.columns(2)
    a.subheader(T["per_day"])
    a.bar_chart(data.groupby("DATE_RECEIVED").size().rename("samples"))
    b.subheader(T["per_machine"])
    b.bar_chart(data.groupby("MACHINE").size().rename("samples"))
    a.subheader(T["per_component"])
    a.bar_chart(data.groupby("COMPONENT").size().rename("samples"))
    b.subheader(T["per_tube"])
    b.bar_chart(data.groupby("TUBE_SIZE").size().rename("samples"))

# ---------- Chatbot (Cortex Analyst over semantic view) ----------
def ask_analyst(messages):
    payload = {"messages": messages, "semantic_view": SEMANTIC_VIEW}
    if _snowflake is not None:
        resp = _snowflake.send_snow_api_request(
            "POST", "/api/v2/cortex/analyst/message", {}, {}, payload, None, 50000)
        status, body = resp["status"], json.loads(resp["content"])
    else:
        # Container runtime: OAuth token file + internal host are provided by Snowflake.
        token_path = "/snowflake/session/token"
        if os.path.exists(token_path):
            token = open(token_path).read().strip()
            headers = {"Authorization": f"Bearer {token}",
                       "X-Snowflake-Authorization-Token-Type": "OAUTH"}
            host = os.environ.get("SNOWFLAKE_HOST") or session.connection.host
        else:
            headers = {"Authorization": f'Snowflake Token="{session.connection.rest.token}"'}
            host = session.connection.host
        r = requests.post(f"https://{host}/api/v2/cortex/analyst/message",
                          json=payload, headers=headers, timeout=60)
        status, body = r.status_code, r.json()
    if status >= 400:
        raise RuntimeError(body.get("message", body))
    return body["message"]


with tab_chat:
    if "msgs" not in st.session_state:
        st.session_state.msgs = []
    for m in st.session_state.msgs:
        with st.chat_message(m["role"]):
            for part in m["content"]:
                if part["type"] == "text":
                    st.markdown(part["text"])
                elif part["type"] == "sql":
                    with st.expander("SQL"):
                        st.code(part["statement"], language="sql")
                    res = q(part["statement"])
                    st.dataframe(res, use_container_width=True)
                    num = res.select_dtypes("number").columns
                    if len(res.columns) == 2 and len(num) == 1 and len(res) > 1:
                        st.bar_chart(res.set_index(res.columns[0]))
    prompt = st.chat_input(T["chat_hint"])
    if prompt:
        st.session_state.msgs.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
        try:
            reply = ask_analyst(st.session_state.msgs)
            st.session_state.msgs.append({"role": "analyst", "content": reply["content"]})
        except Exception as e:  # keep chat usable on API errors
            st.session_state.msgs.pop()
            st.error(str(e))
        st.rerun()

# ---------- Review flagged samples (labels can't be corrected, only flagged) ----------
flagged = pending[pending["IS_DUPLICATE"] | pending["HAS_MISSING_FIELD"] | pending["HAS_BAD_DATE"]].copy()
flagged["FLAG_REASON"] = [
    ", ".join(n for n, f in [("Duplicate ID", d), ("Missing field", m), ("Bad date", b)] if f)
    for d, m, b in zip(flagged["IS_DUPLICATE"], flagged["HAS_MISSING_FIELD"], flagged["HAS_BAD_DATE"])]
with tab_fix:
    if len(flagged):
        st.warning(T["flag_note"].format(n=int((~flagged["UNFLAGGED"]).sum())))
        st.caption(T["unflag_hint"])
        edited = st.data_editor(
            flagged[["UNFLAGGED", "FLAG_REASON", "ROW_ID"] + CSV_COLS + ["TUBE_SIZE"]],
            key="unflag_editor", hide_index=True, use_container_width=True,
            column_config={"UNFLAGGED": st.column_config.CheckboxColumn(T["unflag_col"]),
                           "ROW_ID": None},
            disabled=["FLAG_REASON"] + CSV_COLS + ["TUBE_SIZE"])
        changed = edited[edited["UNFLAGGED"] != flagged["UNFLAGGED"].values]
        if st.button(T["save"], disabled=changed.empty):
            for row_id, val in zip(changed["ROW_ID"], changed["UNFLAGGED"]):
                session.sql(f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET UNFLAGGED = ? WHERE ROW_ID = ?",
                            params=[bool(val), int(row_id)]).collect()
            st.toast(T["saved"])
            st.rerun()
    else:
        st.success(T["no_issues"])


def submit(action: str):
    """Forward pending rows of this batch to MRG_SAMPLES (flags included), then mark them submitted."""
    user = session.sql("SELECT CURRENT_USER()").collect()[0][0]
    n = len(pending)
    session.sql(f"""
        INSERT INTO {DB_SCHEMA}.MRG_SAMPLES
        SELECT SAMPLE_ID, DATE_SAMPLED, DATE_RECEIVED, MACHINE, COMPONENT, SERIAL_NUMBER, REFERENCE_LUBE,
               TUBE_SIZE, BATCH_ID, CURRENT_TIMESTAMP(), ?,
               IS_FLAGGED,
               NULLIF(ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(
                   IFF(IS_DUPLICATE, 'Duplicate ID', NULL),
                   IFF(HAS_MISSING_FIELD, 'Missing field', NULL),
                   IFF(HAS_BAD_DATE, 'Bad date', NULL),
                   IFF(UNFLAGGED AND (IS_DUPLICATE OR HAS_MISSING_FIELD OR HAS_BAD_DATE), '(unflagged by user)', NULL)), ', '), '')
        FROM {DB_SCHEMA}.MRG_VIEW WHERE BATCH_ID = ? AND STATUS = 'PENDING'
    """, params=[user, batch]).collect()
    session.sql(f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'SUBMITTED' WHERE BATCH_ID = ? AND STATUS = 'PENDING'",
                params=[batch]).collect()
    session.sql(f"INSERT INTO {DB_SCHEMA}.SUBMISSION_LOG VALUES (?, CURRENT_TIMESTAMP(), ?, ?, ?)",
                params=[batch, user, n, action]).collect()
    st.session_state.popup = T["submitted"].format(n=n, f=int(flagged_count))


@st.dialog(T["popup_title"])
def submitted_popup(msg: str):
    st.success(msg)
    if st.button("OK"):
        st.rerun()


st.divider()
nothing = len(pending) == 0
flagged_count = pending["IS_FLAGGED"].sum()
if st.button(T["submit"], type="primary", disabled=nothing, use_container_width=True):
    submit("SUBMIT"); st.rerun()
if nothing:
    st.caption(T["nothing"])
if "popup" in st.session_state:
    submitted_popup(st.session_state.pop("popup"))

# ---------- Data: original CSV values beside computed fields ----------
with tab_data:
    st.dataframe(data, use_container_width=True, hide_index=True)

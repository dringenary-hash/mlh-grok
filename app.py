import streamlit as st
import streamlit.components.v1 as components
from google import genai
import pandas as pd
from datetime import date
from PIL import Image
import json
import time
import os
import base64
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine
import snowflake.snowpark as snowpark
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

# _snowflake only exists in the warehouse runtime; local/container uses REST instead.
try:
    import _snowflake
except ImportError:
    _snowflake = None

st.set_page_config(page_title="MRG Labs Label Scanner", layout="wide")

# ---------- Snowflake / Sample Intake config ----------
DB_SCHEMA = os.environ.get("SNOWFLAKE_DB_SCHEMA", "MRG_LABS_DB.INTAKE")
SF_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "MRG_LABS_DB")
SF_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "INTAKE")
SEMANTIC_VIEW = f"{DB_SCHEMA}.MRG_INTAKE_SV"
CSV_COLS = [
    "SAMPLE_ID", "DATE_SAMPLED", "DATE_RECEIVED", "MACHINE", "COMPONENT",
    "SERIAL_NUMBER", "REFERENCE_LUBE",
]
OCR_TO_SF = {
    "Sample ID": "SAMPLE_ID",
    "Date Sampled": "DATE_SAMPLED",
    "Date Received": "DATE_RECEIVED",
    "Machine": "MACHINE",
    "Component": "COMPONENT",
    "Serial Number": "SERIAL_NUMBER",
    "Reference Lube": "REFERENCE_LUBE",
}
TUBE_HEADERS = ["TUBE_SIZE", "TUBE", "SIZE", "TUBE_TYPE"]
TUBE_VALUES = {
    "S": "SMALL", "SM": "SMALL", "SMALL": "SMALL",
    "L": "LARGE", "LG": "LARGE", "LARGE": "LARGE",
}
ALL = "__ALL__"

# Sample Intake UI strings (from updated app2.py)
TEXT = {
    "en": {
        "title": "MRG Laboratories - Sample Intake",
        "upload": "Upload weekly OCR output CSV",
        "loaded": "Loaded {n} rows into batch {b}",
        "batch": "Batch",
        "samples": "Samples", "dups": "Duplicate IDs", "missing": "Missing fields",
        "bad_dates": "Bad dates", "turnaround": "Avg turnaround (days)",
        "tab_dash": "Dashboard", "tab_chat": "Ask the data",
        "tab_flag": "Flagged samples", "tab_data": "Data",
        "per_day": "Samples received per day", "per_machine": "Samples per machine",
        "per_component": "Samples per component", "per_tube": "Small vs Large tubes",
        "chat_hint": "Ask a question, e.g. 'Which machines have the longest turnaround?'",
        "dup_alert": "{n} rows share a Sample ID and are flagged - see the Flagged samples tab.",
        "no_issues": "No flagged samples - ready to submit.",
        "save": "Save flag changes", "saved": "Flag changes saved.",
        "unflag_col": "Unflag",
        "unflag_hint": "Tick 'Unflag' to clear a flag (untick to re-flag), then save.",
        "submit": "Submit to MRG",
        "blocked": "Resolve duplicate Sample IDs before submitting.",
        "submitted": "Your data has been submitted to MRG: {n} samples ({f} flagged for review).",
        "popup_title": "Submitted to MRG",
        "flag_note": "{n} samples are flagged. Labels can't be corrected - they will be submitted with their flag.",
        "nothing": "No pending samples in this batch.",
        "feed": "Server feed", "feed_mode": "Mode", "feed_source": "Source",
        "feed_last": "Last pull", "feed_new": "Rows imported (last pull)",
        "feed_total": "Server rows read so far",
        "feed_pull": "Pull from server now", "feed_sim": "Simulate new server rows",
        "feed_sim_n": "Rows to add", "feed_never": "Never",
        "feed_err": "Last pull failed: {e}",
        "feed_history": "Recent pulls",
        "all_batches": "All batches", "unknown": "Unknown",
        "submit_pick": "Pick a single batch to submit.",
    }
}
LANG = "en"
T = TEXT[LANG]

# Inject MRG Labs CSS Theme and Custom Behaviors
st.markdown("""
    <style>
        :root {
            --mrg-blue: #004B87;
            --mrg-light-blue: #005A9E;
        }
        h1, h2, h3, h4 {
            color: var(--mrg-blue) !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        .stButton>button {
            background-color: var(--mrg-blue);
            color: white;
            border-radius: 4px;
            border: 1px solid var(--mrg-blue);
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            background-color: var(--mrg-light-blue);
            border: 1px solid var(--mrg-light-blue);
            color: white;
        }
        .stDownloadButton>button {
            background-color: #28a745;
            border: 1px solid #28a745;
        }
        .stDownloadButton>button:hover {
            background-color: #218838;
            border: 1px solid #218838;
        }
        [data-testid="stFileUploader"] ul {
            display: none !important;
        }
        .alert-container {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            height: 100%;
            margin-top: 5px;
        }
        .alert-box {
            position: relative;
            padding: 8px 30px 8px 15px;
            background-color: #e6f4ea;
            color: #137333;
            border-radius: 4px;
            border: 1px solid #ceead6;
            font-size: 14px;
        }
        .alert-box .close-btn {
            display: none;
            position: absolute;
            top: 50%;
            right: 8px;
            transform: translateY(-50%);
            cursor: pointer;
            font-size: 12px;
            font-weight: bold;
        }
        .alert-box:hover .close-btn {
            display: block;
        }
        #close-alert { display: none; }
        #close-alert:checked ~ .alert-box { display: none; }
    </style>
""", unsafe_allow_html=True)

st.title("MRG Labs: Sample Label Scanner")

# ---------- Session state ----------
for key, default in {
    "uploader_key": 0,
    "generated_csv": None,
    "csv_filename": None,
    "processed_df": None,
    "last_snowflake_batch": None,
    "msgs": [],
    "chat_batch": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.error("Server Configuration Error: GEMINI_API_KEY environment variable is not set.")
    st.stop()


def get_image_base64(image):
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def get_snowflake_session():
    """Snowpark session with key-pair auth (works outside Snowflake Streamlit runtime)."""
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", "rsa_key.p8")
    with open(key_path, "rb") as key:
        p_key = serialization.load_pem_private_key(
            key.read(),
            password=os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "").encode() or None,
            backend=default_backend(),
        )
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    conn_params = {
        "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
        "user": os.environ.get("SNOWFLAKE_USER"),
        "private_key": pkb,
        "role": os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": SF_DATABASE,
        "schema": SF_SCHEMA,
    }
    missing = [k for k in ("account", "user") if not conn_params.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing Snowflake env vars: {', '.join('SNOWFLAKE_' + m.upper() for m in missing)}"
        )
    return snowpark.Session.builder.configs(conn_params).create()


def normalize_tube_series(tube):
    """Map tube size aliases; keep unrecognized values so they flag as missing tube size."""
    if tube is None:
        return None
    return tube.astype(str).str.strip().str.upper().map(lambda v: TUBE_VALUES.get(v, v))


def ocr_df_to_snowflake_frame(df: pd.DataFrame):
    """Map Gemini OCR / Tiger columns to Snowflake STAGING_SAMPLES."""
    sf_df = df.rename(columns=OCR_TO_SF).copy()
    # Also accept already-uppercased Snowflake columns
    for col in CSV_COLS:
        if col not in sf_df.columns:
            sf_df[col] = None

    tube_col = next((h for h in TUBE_HEADERS if h in sf_df.columns), None)
    if tube_col and tube_col != "TUBE_SIZE":
        sf_df["TUBE_SIZE"] = normalize_tube_series(sf_df[tube_col])
    elif "TUBE_SIZE" in sf_df.columns:
        sf_df["TUBE_SIZE"] = normalize_tube_series(sf_df["TUBE_SIZE"])
    else:
        sf_df["TUBE_SIZE"] = None

    for col in CSV_COLS + ["TUBE_SIZE"]:
        sf_df[col] = sf_df[col].astype(str).where(sf_df[col].notna(), None)
        sf_df[col] = sf_df[col].replace({"None": None, "nan": None, "NaT": None})

    batch = f"BATCH_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
    sf_df["BATCH_ID"] = batch
    return sf_df[CSV_COLS + ["TUBE_SIZE", "BATCH_ID"]], batch


def push_ocr_batch_to_snowflake(df: pd.DataFrame) -> str:
    """Send OCR/Tiger batch into Snowflake STAGING_SAMPLES after Tiger Data."""
    session = get_snowflake_session()
    try:
        sf_df, batch = ocr_df_to_snowflake_frame(df)
        session.write_pandas(
            sf_df,
            "STAGING_SAMPLES",
            database=SF_DATABASE,
            schema=SF_SCHEMA,
            auto_create_table=False,
            overwrite=False,
        )
        session.sql(
            f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'PENDING' WHERE STATUS IS NULL"
        ).collect()
        return batch
    finally:
        session.close()


def sf_query(session, sql: str, params=None) -> pd.DataFrame:
    return session.sql(sql, params=params).to_pandas()


def ask_analyst(session, messages):
    """Cortex Analyst over the MRG intake semantic view."""
    payload = {"messages": messages, "semantic_view": SEMANTIC_VIEW}
    if _snowflake is not None:
        resp = _snowflake.send_snow_api_request(
            "POST", "/api/v2/cortex/analyst/message", {}, {}, payload, None, 50000
        )
        status, body = resp["status"], json.loads(resp["content"])
    else:
        token_path = "/snowflake/session/token"
        if os.path.exists(token_path):
            token = open(token_path).read().strip()
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Snowflake-Authorization-Token-Type": "OAUTH",
            }
            host = os.environ.get("SNOWFLAKE_HOST") or session.connection.host
        else:
            headers = {
                "Authorization": f'Snowflake Token="{session.connection.rest.token}"'
            }
            host = session.connection.host
        r = requests.post(
            f"https://{host}/api/v2/cortex/analyst/message",
            json=payload,
            headers=headers,
            timeout=60,
        )
        status, body = r.status_code, r.json()
    if status >= 400:
        raise RuntimeError(body.get("message", body))
    return body["message"]


def process_label(client, uploaded_file):
    try:
        image = Image.open(uploaded_file)
        image.thumbnail((1024, 1024))

        prompt = """
        You are an OCR and data extraction assistant for a laboratory.
        Analyze the provided image of a sample label. Determine if it is a 'Large' or 'Small' sample label based on the fields present.

        Extract the data to match these exact rules:
        If Large:
        - Sample ID: Barcode or num
        - Date Sampled: Extract the date written (leave blank if empty)
        - Machine: Equip ID
        - Component: Sample point
        - Serial Number: (leave blank)
        - Reference Lube: Ref Lube

        If Small:
        - Sample ID: Barcode or num
        - Date Sampled: Extract the date written
        - Machine: RN
        - Component: Circled num + circled GS/NGS
        - Serial Number: SN
        - Reference Lube: (leave blank)

        Return ONLY a raw JSON object (no markdown formatting, no backticks) with exactly these keys:
        "Sample ID", "Date Sampled", "Machine", "Component", "Serial Number", "Reference Lube"
        """

        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[prompt, image],
                )
                break
            except Exception as api_error:
                if "503" in str(api_error) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                elif attempt == 2:
                    raise api_error

        response_text = response.text.strip().strip("```json").strip("```")
        extracted_data = json.loads(response_text)
        extracted_data["Filename"] = uploaded_file.name
        extracted_data["Date Received"] = date.today().strftime("%m/%d/%Y")
        extracted_data["Status"] = "Success"
        return extracted_data
    except Exception as e:
        return {
            "Filename": uploaded_file.name,
            "Sample ID": "ERROR",
            "Status": f"Failed: {str(e)}",
        }


tab1, tab2, tab3 = st.tabs(["Image Upload", "Data Viewer", "Snowflake Intake"])

# ===== TAB 1: OCR → Tiger Data → Snowflake =====
with tab1:
    col_text, col_btn = st.columns([3, 1])
    with col_text:
        st.markdown(
            "<h4 style='margin-top: 0.5rem;'>Upload Label Images (JPG, PNG)</h4>",
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button("Clear All", use_container_width=True):
            st.session_state.uploader_key += 1
            st.session_state.generated_csv = None
            st.session_state.processed_df = None
            st.rerun()

    uploaded_files = st.file_uploader(
        "Upload Label Images (JPG, PNG)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
        label_visibility="collapsed",
    )

    if uploaded_files:
        st.write(f"**{len(uploaded_files)} images ready to process.**")
        user_file_name = st.text_input("Enter CSV file name:", "bulk_lab_samples_output")

        if st.button("Process All Labels"):
            client = genai.Client(api_key=api_key)
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_label, client, f) for f in uploaded_files]
                for i, future in enumerate(as_completed(futures)):
                    results.append(future.result())
                    progress_bar.progress((i + 1) / len(uploaded_files))
                    status_text.text(f"Processed {i + 1} of {len(uploaded_files)} labels...")

            columns = [
                "Sample ID", "Date Sampled", "Date Received",
                "Machine", "Component", "Serial Number", "Reference Lube",
            ]
            df = pd.DataFrame(results).reindex(columns=columns)
            df["Date Sampled"] = pd.to_datetime(df["Date Sampled"], errors="coerce").dt.date

            # 1) Tiger Data
            db_uri = os.environ.get("TIGERDATA_URI")
            if db_uri:
                try:
                    engine = create_engine(db_uri)
                    df.to_sql("lab_samples", con=engine, if_exists="append", index=False)
                    st.toast("Wrote batch to Tiger Data")
                except Exception as e:
                    st.error(f"Failed to write to Tiger Data: {e}")
            else:
                st.warning("TIGERDATA_URI is not set — skipped Tiger Data write.")

            # 2) Snowflake
            try:
                batch_id = push_ocr_batch_to_snowflake(df)
                st.session_state.last_snowflake_batch = batch_id
                st.toast(f"Synced batch {batch_id} to Snowflake")
            except Exception as e:
                st.error(f"Failed to write to Snowflake: {e}")

            st.session_state.processed_df = df
            st.session_state.generated_csv = df.to_csv(index=False).encode("utf-8")
            st.session_state.csv_filename = f"{user_file_name}.csv"
            st.session_state.uploader_key += 1
            st.rerun()

    if st.session_state.generated_csv is not None:
        st.success("All labels processed successfully! The upload area has been cleared for your next batch.")
        if st.session_state.last_snowflake_batch:
            st.info(
                f"Latest Snowflake batch: `{st.session_state.last_snowflake_batch}` "
                "— open the **Snowflake Intake** tab to review / chat."
            )
        st.dataframe(st.session_state.processed_df)
        st.download_button(
            label="Download Combined CSV",
            data=st.session_state.generated_csv,
            file_name=st.session_state.csv_filename,
            mime="text/csv",
        )

    # --- MINESWEEPER COMPONENT ---
    st.markdown("---")
    st.markdown(
        "<h5 style='text-align: center; color: #004B87;'>Waiting for images to process? Play a round!</h5>",
        unsafe_allow_html=True,
    )
    minesweeper_html = """
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 0; padding-top: 10px; color: #333; }
        #board { display: grid; grid-template-columns: repeat(10, 30px); gap: 2px; margin-top: 10px; }
        .cell { width: 30px; height: 30px; background-color: #f0f2f6; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; cursor: pointer; border-radius: 4px; user-select: none; }
        .cell:hover { background-color: #e0e2e6; }
        .cell.revealed { background-color: #ffffff; border: 1px solid #ddd; cursor: default; box-sizing: border-box; }
        .cell.mine { background-color: #ffcccc; }
        #status { margin-top: 15px; font-weight: bold; min-height: 20px; color: #004B87; }
        button { margin-top: 10px; padding: 8px 16px; border: none; background: #004B87; color: white; border-radius: 4px; cursor: pointer; font-size: 14px; transition: all 0.3s ease; }
        button:hover { background: #005A9E; }
    </style>
    </head>
    <body>
        <div id="board"></div>
        <div id="status"></div>
        <button onclick="initGame()">Restart Game</button>
        <script>
            const size = 10;
            const mineCount = 12;
            let board = [];
            let revealed = 0;
            let gameOver = false;

            function initGame() {
                board = Array(size).fill().map(() => Array(size).fill({ mine: false, revealed: false, flag: false, count: 0 }));
                gameOver = false;
                revealed = 0;
                document.getElementById('status').innerText = "Right-click to flag mines";
                let minesPlaced = 0;
                while (minesPlaced < mineCount) {
                    let r = Math.floor(Math.random() * size);
                    let c = Math.floor(Math.random() * size);
                    if (!board[r][c].mine) {
                        board[r][c] = { ...board[r][c], mine: true };
                        minesPlaced++;
                    }
                }
                for (let r = 0; r < size; r++) {
                    for (let c = 0; c < size; c++) {
                        if (!board[r][c].mine) {
                            let count = 0;
                            for (let dr = -1; dr <= 1; dr++) {
                                for (let dc = -1; dc <= 1; dc++) {
                                    if (r+dr >= 0 && r+dr < size && c+dc >= 0 && c+dc < size && board[r+dr][c+dc].mine) count++;
                                }
                            }
                            board[r][c] = { ...board[r][c], count };
                        }
                    }
                }
                render();
            }

            function render() {
                const b = document.getElementById('board');
                b.innerHTML = '';
                for (let r = 0; r < size; r++) {
                    for (let c = 0; c < size; c++) {
                        let cell = document.createElement('div');
                        cell.className = 'cell';
                        if (board[r][c].revealed) {
                            cell.classList.add('revealed');
                            if (board[r][c].mine) {
                                cell.classList.add('mine');
                                cell.innerText = '💣';
                            } else if (board[r][c].count > 0) {
                                cell.innerText = board[r][c].count;
                                const colors = ['#0000FF', '#008000', '#FF0000', '#000080', '#800000', '#008080', '#000000', '#808080'];
                                cell.style.color = colors[board[r][c].count - 1];
                            }
                        } else if (board[r][c].flag) {
                            cell.innerText = '🚩';
                        }
                        cell.onclick = () => reveal(r, c);
                        cell.oncontextmenu = (e) => { e.preventDefault(); toggleFlag(r, c); };
                        b.appendChild(cell);
                    }
                }
            }

            function reveal(r, c) {
                if (gameOver || board[r][c].revealed || board[r][c].flag) return;
                let cell = board[r][c];
                cell.revealed = true;
                if (cell.mine) {
                    gameOver = true;
                    document.getElementById('status').innerText = "Boom! Game Over.";
                    document.getElementById('status').style.color = "red";
                    revealAll();
                } else {
                    revealed++;
                    if (revealed === size * size - mineCount) {
                        gameOver = true;
                        document.getElementById('status').innerText = "You Win! 🏆";
                        document.getElementById('status').style.color = "green";
                    } else if (cell.count === 0) {
                        for (let dr = -1; dr <= 1; dr++) {
                            for (let dc = -1; dc <= 1; dc++) {
                                if (r+dr >= 0 && r+dr < size && c+dc >= 0 && c+dc < size) reveal(r+dr, c+dc);
                            }
                        }
                    }
                }
                render();
            }

            function toggleFlag(r, c) {
                if (gameOver || board[r][c].revealed) return;
                board[r][c].flag = !board[r][c].flag;
                render();
            }

            function revealAll() {
                for (let r = 0; r < size; r++) {
                    for (let c = 0; c < size; c++) {
                        board[r][c].revealed = true;
                    }
                }
            }
            initGame();
        </script>
    </body>
    </html>
    """
    components.html(minesweeper_html, height=450)

# ===== TAB 2: Tiger Data viewer =====
with tab2:
    st.subheader("Live Database Records")
    col_btn, col_status = st.columns([1, 1])
    with col_btn:
        st.button("Refresh Table", use_container_width=False)
    with col_status:
        st.markdown("""
            <div class="alert-container">
                <input type="checkbox" id="close-alert">
                <div class="alert-box">
                    Successfully connected!
                    <label for="close-alert" class="close-btn">✖</label>
                </div>
            </div>
        """, unsafe_allow_html=True)

    try:
        db_uri = os.environ.get("TIGERDATA_URI")
        if db_uri:
            engine = create_engine(db_uri)
            db_df = pd.read_sql_table("lab_samples", con=engine)

            st.markdown("##### Filter Data")
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                machine_filter = st.text_input("Filter by Machine (leave blank for all)")
            with filter_col2:
                available_components = db_df["Component"].dropna().unique().tolist()
                comp_filter = st.multiselect("Filter by Component", options=available_components)

            filtered_df = db_df.copy()
            if machine_filter:
                filtered_df = filtered_df[
                    filtered_df["Machine"].astype(str).str.contains(
                        machine_filter, case=False, na=False
                    )
                ]
            if comp_filter:
                filtered_df = filtered_df[filtered_df["Component"].isin(comp_filter)]

            st.dataframe(filtered_df.tail(100), use_container_width=True)
            st.divider()
            st.caption(
                "For Snowflake Cortex Analyst chat (copied / missing entries, duplicates, turnaround), "
                "use the **Snowflake Intake** tab."
            )
            if st.button("Sync filtered Tiger rows to Snowflake now", use_container_width=True):
                try:
                    needed = list(OCR_TO_SF.keys())
                    sync_df = filtered_df.copy()
                    for col in needed:
                        if col not in sync_df.columns:
                            sync_df[col] = None
                    batch_id = push_ocr_batch_to_snowflake(sync_df[needed])
                    st.session_state.last_snowflake_batch = batch_id
                    st.success(f"Synced {len(sync_df)} rows to Snowflake as `{batch_id}`")
                except Exception as e:
                    st.error(f"Snowflake sync failed: {e}")
        else:
            st.warning("TIGERDATA_URI environment variable is not set.")
    except Exception as e:
        st.error(f"Could not connect to database: {e}")

# ===== TAB 3: Updated Sample Intake (app2) + key-pair Snowflake session =====
with tab3:
    st.subheader(T["title"])
    st.caption(
        "Review batches synced from OCR → Tiger Data → Snowflake. "
        "Ask Cortex Analyst about copied datasets, missing fields, duplicates, and turnaround."
    )

    try:
        session = get_snowflake_session()
    except Exception as e:
        st.error(f"Could not connect to Snowflake: {e}")
        st.info(
            "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and place `rsa_key.p8` in the app directory "
            "(or set SNOWFLAKE_PRIVATE_KEY_PATH)."
        )
        st.stop()

    def q(sql: str, params=None) -> pd.DataFrame:
        return sf_query(session, sql, params=params)

    try:
        # ---------- Server feed ----------
        with st.expander(T["feed"], expanded=True):
            try:
                cfg = q(f"SELECT MODE, SOURCE_URL, SIM_FILE FROM {DB_SCHEMA}.FEED_CONFIG").iloc[0]
                runs = q(f"SELECT * FROM {DB_SCHEMA}.FEED_RUN_LOG ORDER BY RUN_AT DESC LIMIT 10")
                state = q(f"SELECT LAST_ROW_NUMBER FROM {DB_SCHEMA}.FEED_STATE")
                src = (
                    cfg["SOURCE_URL"]
                    if cfg["MODE"] == "LIVE"
                    else f"@SIM_SERVER/{cfg['SIM_FILE']} (stand-in for {cfg['SOURCE_URL']})"
                )
                k = st.columns(4)
                k[0].metric(T["feed_mode"], cfg["MODE"])
                k[1].metric(
                    T["feed_last"],
                    f"{runs.iloc[0]['RUN_AT']:%b %d %H:%M}" if len(runs) else T["feed_never"],
                )
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
                    n_add = b3.number_input(
                        T["feed_sim_n"], 1, 500, 50, label_visibility="collapsed"
                    )
                    if b2.button(T["feed_sim"], use_container_width=True):
                        st.toast(
                            session.sql(
                                f"CALL {DB_SCHEMA}.SIMULATE_SERVER_APPEND({int(n_add)})"
                            ).collect()[0][0]
                        )
                if "feed_msg" in st.session_state:
                    m = st.session_state.pop("feed_msg")
                    (st.error if m.startswith("ERROR") else st.success)(m)
                if len(runs):
                    st.caption(T["feed_history"])
                    st.dataframe(
                        runs[["RUN_AT", "ROWS_READ", "ROWS_NEW", "METHOD", "BATCH_ID", "ERROR"]],
                        hide_index=True,
                        use_container_width=True,
                    )
            except Exception as feed_err:
                st.warning(f"Server feed unavailable: {feed_err}")

        # ---------- Manual CSV upload ----------
        with st.expander(T["upload"]):
            f = st.file_uploader(
                "CSV", type="csv", label_visibility="collapsed", key="sf_csv_upload"
            )
            if f is not None and st.button("Load"):
                up_df = pd.read_csv(f, dtype=str)
                up_df.columns = [c.strip().upper().replace(" ", "_") for c in up_df.columns]
                tube_col = next((h for h in TUBE_HEADERS if h in up_df.columns), None)
                tube = up_df[tube_col] if tube_col else None
                up_df = up_df.reindex(columns=CSV_COLS)
                up_df["TUBE_SIZE"] = normalize_tube_series(tube)
                batch_id = f"BATCH_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
                up_df["BATCH_ID"] = batch_id
                session.write_pandas(
                    up_df,
                    "STAGING_SAMPLES",
                    database=SF_DATABASE,
                    schema=SF_SCHEMA,
                    auto_create_table=False,
                    overwrite=False,
                )
                session.sql(
                    f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'PENDING' WHERE STATUS IS NULL"
                ).collect()
                st.session_state.last_snowflake_batch = batch_id
                st.success(T["loaded"].format(n=len(up_df), b=batch_id))

        batches = q(
            f"SELECT DISTINCT BATCH_ID FROM {DB_SCHEMA}.STAGING_SAMPLES ORDER BY 1 DESC"
        )["BATCH_ID"].tolist()

        if not batches:
            st.info("No pending samples in Snowflake yet. Process labels on the Image Upload tab first.")
        else:
            default_idx = 0
            if st.session_state.last_snowflake_batch in batches:
                default_idx = batches.index(st.session_state.last_snowflake_batch)

            batch = st.selectbox(
                T["batch"],
                batches + [ALL],
                index=default_idx,
                format_func=lambda b: T["all_batches"] if b == ALL else b,
            )

            # Scope chatbot view to the batch on screen
            if st.session_state.get("chat_batch") != batch:
                try:
                    session.sql(
                        f"""MERGE INTO {DB_SCHEMA}.CHAT_BATCH_SELECTION t
                            USING (SELECT CURRENT_USER() AS U) s ON t.USER_NAME = s.U
                            WHEN MATCHED THEN UPDATE SET BATCH_ID = ?, UPDATED_AT = CURRENT_TIMESTAMP()
                            WHEN NOT MATCHED THEN INSERT VALUES (s.U, ?, CURRENT_TIMESTAMP())""",
                        params=[batch, batch],
                    ).collect()
                except Exception as sel_err:
                    st.caption(f"Chat batch selection note: {sel_err}")
                st.session_state.chat_batch = batch

            data = (
                q(f"SELECT * FROM {DB_SCHEMA}.MRG_VIEW")
                if batch == ALL
                else q(f"SELECT * FROM {DB_SCHEMA}.MRG_VIEW WHERE BATCH_ID = ?", [batch])
            )
            pending = data[data["STATUS"] == "PENDING"] if "STATUS" in data.columns else data
            dup_rows = (
                pending[pending["IS_DUPLICATE"]]
                if "IS_DUPLICATE" in pending.columns
                else pending.iloc[0:0]
            )

            c = st.columns(5)
            c[0].metric(T["samples"], len(data))
            c[1].metric(
                T["dups"],
                int(data["IS_DUPLICATE"].sum()) if "IS_DUPLICATE" in data else 0,
            )
            c[2].metric(
                T["missing"],
                int(data["HAS_MISSING_FIELD"].sum()) if "HAS_MISSING_FIELD" in data else 0,
            )
            c[3].metric(
                T["bad_dates"],
                int(data["HAS_BAD_DATE"].sum()) if "HAS_BAD_DATE" in data else 0,
            )
            turnaround = (
                round(float(data["TURNAROUND_DAYS"].mean() or 0), 1)
                if "TURNAROUND_DAYS" in data and len(data)
                else 0
            )
            c[4].metric(T["turnaround"], turnaround)

            if len(dup_rows):
                st.warning(T["dup_alert"].format(n=len(dup_rows)))

            tab_dash, tab_chat, tab_flag, tab_data = st.tabs(
                [T["tab_dash"], T["tab_chat"], T["tab_flag"], T["tab_data"]]
            )

            with tab_dash:
                a, b = st.columns(2)
                if "DATE_RECEIVED" in data.columns:
                    a.subheader(T["per_day"])
                    a.bar_chart(data.groupby("DATE_RECEIVED").size().rename("samples"))
                machine_col = "NORM_MACHINE" if "NORM_MACHINE" in data.columns else "MACHINE"
                if machine_col in data.columns:
                    b.subheader(T["per_machine"])
                    b.bar_chart(data.groupby(machine_col).size().rename("samples"))
                if "COMPONENT" in data.columns:
                    a.subheader(T["per_component"])
                    a.bar_chart(data.groupby("COMPONENT").size().rename("samples"))
                if "TUBE_SIZE" in data.columns:
                    b.subheader(T["per_tube"])
                    b.bar_chart(
                        data["TUBE_SIZE"].fillna(T["unknown"]).value_counts().rename("samples")
                    )

            def batch_context() -> str:
                if batch == ALL:
                    return (
                        f"Context: the user is viewing ALL batches "
                        f"({len(data)} samples in total)."
                    )
                return (
                    f"Context: the user is viewing batch {batch} ({len(data)} samples). "
                    "The data is already limited to this batch; count only these samples."
                )

            with tab_chat:
                st.caption(batch_context().replace("Context: the user is", "Answering about"))
                for m in st.session_state.msgs:
                    with st.chat_message(m["role"]):
                        if m.get("batch_label"):
                            st.caption(m["batch_label"])
                        for part in m["content"]:
                            if part["type"] == "text":
                                st.markdown(part["text"])
                            elif part["type"] == "sql":
                                with st.expander("SQL"):
                                    st.code(part["statement"], language="sql")
                                res = part.get("result")
                                if res is None:
                                    continue
                                st.dataframe(res, use_container_width=True)
                                num = res.select_dtypes("number").columns
                                if len(res.columns) == 2 and len(num) == 1 and len(res) > 1:
                                    st.bar_chart(res.set_index(res.columns[0]))

                prompt = st.chat_input(T["chat_hint"])
                if prompt:
                    st.session_state.msgs.append(
                        {"role": "user", "content": [{"type": "text", "text": prompt}]}
                    )
                    api_msgs = [
                        {
                            "role": m["role"],
                            "content": [
                                {k: v for k, v in p.items() if k != "result"}
                                for p in m["content"]
                            ],
                        }
                        for m in st.session_state.msgs
                    ]
                    api_msgs[-1]["content"] = [
                        {"type": "text", "text": f"{batch_context()}\n\nQuestion: {prompt}"}
                    ]
                    try:
                        reply = ask_analyst(session, api_msgs)
                        for part in reply["content"]:
                            if part["type"] == "sql":
                                part["result"] = q(part["statement"])
                        label = T["all_batches"] if batch == ALL else batch
                        st.session_state.msgs.append(
                            {
                                "role": "analyst",
                                "content": reply["content"],
                                "batch_label": label,
                            }
                        )
                    except Exception as e:
                        st.session_state.msgs.pop()
                        st.error(str(e))
                    st.rerun()

            if "HAS_ANY_ISSUE" in pending.columns:
                flagged = pending[pending["HAS_ANY_ISSUE"]].copy()
            elif {"IS_DUPLICATE", "HAS_MISSING_FIELD", "HAS_BAD_DATE"}.issubset(pending.columns):
                flagged = pending[
                    pending["IS_DUPLICATE"]
                    | pending["HAS_MISSING_FIELD"]
                    | pending["HAS_BAD_DATE"]
                ].copy()
                if "FLAG_REASON" not in flagged.columns:
                    flagged["FLAG_REASON"] = [
                        ", ".join(
                            n
                            for n, flag in [
                                ("Duplicate ID", d),
                                ("Missing field", m),
                                ("Bad date", b),
                            ]
                            if flag
                        )
                        for d, m, b in zip(
                            flagged["IS_DUPLICATE"],
                            flagged["HAS_MISSING_FIELD"],
                            flagged["HAS_BAD_DATE"],
                        )
                    ]
            else:
                flagged = pending.iloc[0:0]

            with tab_flag:
                if len(flagged):
                    if "UNFLAGGED" in flagged.columns:
                        st.warning(
                            T["flag_note"].format(n=int((~flagged["UNFLAGGED"]).sum()))
                        )
                        st.caption(T["unflag_hint"])
                        show_cols = ["UNFLAGGED"]
                        if "FLAG_REASON" in flagged.columns:
                            show_cols.append("FLAG_REASON")
                        show_cols.append("ROW_ID")
                        if "BATCH_ID" in flagged.columns:
                            show_cols.append("BATCH_ID")
                        show_cols += CSV_COLS + ["TUBE_SIZE"]
                        show_cols = [c for c in show_cols if c in flagged.columns]
                        disabled = [
                            c
                            for c in show_cols
                            if c != "UNFLAGGED"
                        ]
                        edited = st.data_editor(
                            flagged[show_cols],
                            key="unflag_editor",
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "UNFLAGGED": st.column_config.CheckboxColumn(T["unflag_col"]),
                                "ROW_ID": None,
                            },
                            disabled=disabled,
                        )
                        changed = edited[edited["UNFLAGGED"] != flagged["UNFLAGGED"].values]
                        if st.button(T["save"], disabled=changed.empty):
                            for row_id, val in zip(changed["ROW_ID"], changed["UNFLAGGED"]):
                                session.sql(
                                    f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES "
                                    f"SET UNFLAGGED = ? WHERE ROW_ID = ?",
                                    params=[bool(val), int(row_id)],
                                ).collect()
                            st.toast(T["saved"])
                            st.rerun()
                    else:
                        st.dataframe(flagged, use_container_width=True, hide_index=True)
                else:
                    st.success(T["no_issues"])

            with tab_data:
                st.dataframe(data, use_container_width=True, hide_index=True)

            st.divider()
            nothing = len(pending) == 0
            flagged_count = (
                int(pending["IS_FLAGGED"].sum())
                if "IS_FLAGGED" in pending.columns and len(pending)
                else 0
            )

            def submit(action: str):
                user = session.sql("SELECT CURRENT_USER()").collect()[0][0]
                n = len(pending)
                session.sql(
                    f"""
                    INSERT INTO {DB_SCHEMA}.MRG_SAMPLES
                    SELECT SAMPLE_ID, DATE_SAMPLED, DATE_RECEIVED, MACHINE, COMPONENT,
                           SERIAL_NUMBER, REFERENCE_LUBE, TUBE_SIZE, BATCH_ID,
                           CURRENT_TIMESTAMP(), ?,
                           IS_FLAGGED,
                           NULLIF(TRIM(COALESCE(FLAG_REASON, '') ||
                               IFF(UNFLAGGED AND HAS_ANY_ISSUE, ' (unflagged by user)', '')), '')
                    FROM {DB_SCHEMA}.MRG_VIEW
                    WHERE BATCH_ID = ? AND STATUS = 'PENDING'
                    """,
                    params=[user, batch],
                ).collect()
                session.sql(
                    f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'SUBMITTED' "
                    f"WHERE BATCH_ID = ? AND STATUS = 'PENDING'",
                    params=[batch],
                ).collect()
                session.sql(
                    f"INSERT INTO {DB_SCHEMA}.SUBMISSION_LOG "
                    f"VALUES (?, CURRENT_TIMESTAMP(), ?, ?, ?)",
                    params=[batch, user, n, action],
                ).collect()
                st.session_state.popup = T["submitted"].format(n=n, f=int(flagged_count))

            @st.dialog(T["popup_title"])
            def submitted_popup(msg: str):
                st.success(msg)
                if st.button("OK"):
                    st.rerun()

            if st.button(
                T["submit"],
                type="primary",
                disabled=nothing or batch == ALL,
                use_container_width=True,
            ):
                submit("SUBMIT")
                st.rerun()
            if batch == ALL:
                st.caption(T["submit_pick"])
            elif nothing:
                st.caption(T["nothing"])
            if "popup" in st.session_state:
                submitted_popup(st.session_state.pop("popup"))

    except Exception as e:
        st.error(f"Snowflake Intake error: {e}")
    finally:
        try:
            session.close()
        except Exception:
            pass

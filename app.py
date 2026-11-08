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

# Load local secrets from .env if present (file is gitignored)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# _snowflake only exists in the warehouse runtime; local/container uses REST instead.
try:
    import _snowflake
except ImportError:
    _snowflake = None

# Configure the Streamlit page
st.set_page_config(page_title="MRG Labs Label Scanner", layout="wide")

# Snowflake intake schema used by the Sample Intake review / Cortex Analyst chatbot
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

# Inject MRG Labs CSS Theme and Custom Behaviors
st.markdown("""
    <style>
        /* MRG Labs Brand Styling */
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

        /* Hide Streamlit's default uploaded files list with the blank icons */
        [data-testid="stFileUploader"] ul {
            display: none !important;
        }

        /* Inline Status Message Styling */
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

# Initialize session state variables
if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0
if 'generated_csv' not in st.session_state:
    st.session_state.generated_csv = None
if 'csv_filename' not in st.session_state:
    st.session_state.csv_filename = None
if 'processed_df' not in st.session_state:
    st.session_state.processed_df = None
if 'last_snowflake_batch' not in st.session_state:
    st.session_state.last_snowflake_batch = None
if 'msgs' not in st.session_state:
    st.session_state.msgs = []
if 'grok_qc_report' not in st.session_state:
    st.session_state.grok_qc_report = None
if 'grok_qc_error' not in st.session_state:
    st.session_state.grok_qc_error = None

api_key = os.environ.get("GEMINI_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
GROK_QC_LOG = os.environ.get("GROK_QC_LOG", "grok_qc_log.md")

if not api_key:
    st.error("Server Configuration Error: GEMINI_API_KEY environment variable is not set.")
    st.stop()


def get_image_base64(image):
    """Helper function to convert PIL Image to base64 for custom HTML rendering."""
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def get_snowflake_session():
    """Create a Snowpark session with key-pair auth (same pattern as the original app.py)."""
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


def ocr_df_to_snowflake_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Map Gemini OCR columns to the Snowflake intake staging schema."""
    sf_df = df.rename(columns=OCR_TO_SF).copy()
    for col in CSV_COLS:
        if col not in sf_df.columns:
            sf_df[col] = None
    if "TUBE_SIZE" not in sf_df.columns:
        sf_df["TUBE_SIZE"] = None
    # Snowflake staging expects strings for OCR fields
    for col in CSV_COLS + ["TUBE_SIZE"]:
        sf_df[col] = sf_df[col].astype(str).where(sf_df[col].notna(), None)
        sf_df[col] = sf_df[col].replace({"None": None, "nan": None, "NaT": None})
    batch = f"BATCH_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
    sf_df["BATCH_ID"] = batch
    return sf_df[CSV_COLS + ["TUBE_SIZE", "BATCH_ID"]], batch


def push_ocr_batch_to_snowflake(df: pd.DataFrame) -> str:
    """Send the OCR CSV batch into Snowflake STAGING_SAMPLES after Tiger Data."""
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


def build_batch_qc_stats(df: pd.DataFrame) -> dict:
    """Lightweight batch stats sent to Grok for automated QC (no raw images)."""
    work = df.copy()
    for col in [
        "Sample ID", "Date Sampled", "Date Received",
        "Machine", "Component", "Serial Number", "Reference Lube",
    ]:
        if col not in work.columns:
            work[col] = None

    sample_ids = work["Sample ID"].astype(str)
    missing_sample_id = int(((sample_ids == "") | sample_ids.isna() | (sample_ids == "nan") | (sample_ids == "ERROR")).sum())
    dup_ids = sample_ids[sample_ids.duplicated(keep=False) & ~sample_ids.isin(["", "nan", "ERROR", "None"])]
    missing_fields = {
        col: int(work[col].isna().sum() + (work[col].astype(str).str.strip() == "").sum())
        for col in ["Date Sampled", "Machine", "Component", "Serial Number", "Reference Lube"]
    }
    failed = int(work.get("Status", pd.Series(dtype=str)).astype(str).str.startswith("Failed").sum()) if "Status" in work.columns else 0

    preview_cols = [c for c in [
        "Sample ID", "Date Sampled", "Date Received", "Machine", "Component",
        "Serial Number", "Reference Lube",
    ] if c in work.columns]
    preview = work[preview_cols].head(15).fillna("").astype(str).to_dict(orient="records")

    return {
        "row_count": int(len(work)),
        "failed_ocr_rows": failed,
        "missing_or_error_sample_ids": missing_sample_id,
        "duplicate_sample_id_count": int(dup_ids.nunique()),
        "duplicate_sample_ids": sorted(dup_ids.dropna().astype(str).unique().tolist())[:20],
        "missing_field_counts": missing_fields,
        "preview_rows": preview,
    }


def run_grok_batch_qc(df: pd.DataFrame, batch_id: str | None = None) -> str:
    """
    Auto QC via xAI Grok chat completions.
    XAI_API_KEY authenticates to https://api.x.ai/v1/chat/completions so Grok can
    review batch stats and return a short readiness report.
    """
    if not XAI_API_KEY:
        raise RuntimeError(
            "XAI_API_KEY (or GROK_API_KEY) is not set — cannot run Grok automation."
        )

    stats = build_batch_qc_stats(df)
    system = (
        "You are Grok, the automated QC reviewer for MRG Laboratories sample intake. "
        "Given batch statistics from OCR → Tiger Data → Snowflake, produce a concise "
        "ops report. Flag missing entries, duplicate Sample IDs, and OCR failures. "
        "End with a clear READY TO SUBMIT or NEEDS REVIEW decision and 2-4 bullet actions."
    )
    user = (
        f"Batch ID: {batch_id or 'UNKNOWN'}\n"
        f"Pipeline: Gemini OCR → Tiger Data → Snowflake STAGING_SAMPLES\n"
        f"Stats JSON:\n{json.dumps(stats, default=str)}"
    )

    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROK_MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Grok API error {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    report = body["choices"][0]["message"]["content"].strip()

    # Persist evidence for SpaceXSI / hackathon documentation
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(GROK_QC_LOG, "a", encoding="utf-8") as log:
        log.write(
            f"\n## Grok QC — {stamp}\n"
            f"- Model: `{GROK_MODEL}`\n"
            f"- Batch: `{batch_id or 'UNKNOWN'}`\n"
            f"- Rows: {stats['row_count']}\n"
            f"- Duplicates: {stats['duplicate_sample_id_count']}\n"
            f"- Missing/error Sample IDs: {stats['missing_or_error_sample_ids']}\n\n"
            f"{report}\n\n---\n"
        )
    return report


def sf_query(session, sql: str, params=None) -> pd.DataFrame:
    return session.sql(sql, params=params).to_pandas()


def ask_analyst(session, messages):
    """Cortex Analyst over the MRG intake semantic view (from Sample Intake)."""
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

        max_retries = 3
        response = None

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model='gemini-3.8-flash',
                    contents=[prompt, image]
                )
                break
            except Exception as api_error:
                if '503' in str(api_error) and attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                elif attempt == max_retries - 1:
                    raise api_error

        response_text = response.text.strip().strip('```json').strip('```')
        extracted_data = json.loads(response_text)

        extracted_data["Filename"] = uploaded_file.name
        extracted_data["Date Received"] = date.today().strftime("%m/%d/%Y")
        extracted_data["Status"] = "Success"

        return extracted_data

    except Exception as e:
        return {
            "Filename": uploaded_file.name,
            "Sample ID": "ERROR",
            "Status": f"Failed: {str(e)}"
        }


tab1, tab2, tab3 = st.tabs(["Image Upload", "Data Viewer", "Snowflake Intake"])

with tab1:
    col_text, col_btn = st.columns([3, 1])
    with col_text:
        st.markdown("<h4 style='margin-top: 0.5rem;'>Upload Label Images (JPG, PNG)</h4>", unsafe_allow_html=True)
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
        label_visibility="collapsed"
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
                    result = future.result()
                    results.append(result)
                    current_progress = (i + 1) / len(uploaded_files)
                    progress_bar.progress(current_progress)
                    status_text.text(f"Processed {i + 1} of {len(uploaded_files)} labels...")

            columns = [
                "Sample ID", "Date Sampled", "Date Received",
                "Machine", "Component", "Serial Number", "Reference Lube",
            ]

            df = pd.DataFrame(results)
            df = df.reindex(columns=columns)

            df['Date Sampled'] = pd.to_datetime(df['Date Sampled'], errors='coerce').dt.date

            # 1) Send CSV/data to Tiger Data
            db_uri = os.environ.get("TIGERDATA_URI")
            if db_uri:
                try:
                    engine = create_engine(db_uri)
                    df.to_sql('lab_samples', con=engine, if_exists='append', index=False)
                    st.toast("Wrote batch to Tiger Data")
                except Exception as e:
                    st.error(f"Failed to write to Tiger Data: {e}")
            else:
                st.warning("TIGERDATA_URI is not set — skipped Tiger Data write.")

            # 2) Then send the same batch to Snowflake intake staging
            batch_id = None
            try:
                batch_id = push_ocr_batch_to_snowflake(df)
                st.session_state.last_snowflake_batch = batch_id
                st.toast(f"Synced batch {batch_id} to Snowflake")
            except Exception as e:
                st.error(f"Failed to write to Snowflake: {e}")

            # 3) Auto-run Grok QC automation on the finished batch
            st.session_state.grok_qc_report = None
            st.session_state.grok_qc_error = None
            try:
                with st.spinner("Grok automation: reviewing batch QC…"):
                    st.session_state.grok_qc_report = run_grok_batch_qc(df, batch_id)
                st.toast("Grok QC complete")
            except Exception as e:
                st.session_state.grok_qc_error = str(e)
                st.warning(f"Grok automation skipped/failed: {e}")

            st.session_state.processed_df = df
            st.session_state.generated_csv = df.to_csv(index=False).encode('utf-8')
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

        # Grok automation output (auto-run after each Process All Labels)
        st.markdown("#### 🤖 Grok Automation — Batch QC")
        if st.session_state.grok_qc_report:
            st.success("Grok auto-reviewed this batch after Tiger Data + Snowflake sync.")
            st.markdown(st.session_state.grok_qc_report)
            st.caption(f"Logged to `{GROK_QC_LOG}` · model `{GROK_MODEL}`")
        elif st.session_state.grok_qc_error:
            st.error(f"Grok QC error: {st.session_state.grok_qc_error}")
            st.caption("Set `XAI_API_KEY` in the environment, then re-process a batch.")
        else:
            st.info("Grok QC will auto-run the next time you process labels.")

    # --- MINESWEEPER COMPONENT ---
    st.markdown("---")
    st.markdown("<h5 style='text-align: center; color: #004B87;'>Waiting for images to process? Play a round!</h5>", unsafe_allow_html=True)

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
            db_df = pd.read_sql_table('lab_samples', con=engine)

            st.markdown("##### Filter Data")
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                machine_filter = st.text_input("Filter by Machine (leave blank for all)")
            with filter_col2:
                available_components = db_df['Component'].dropna().unique().tolist()
                comp_filter = st.multiselect("Filter by Component", options=available_components)

            filtered_df = db_df.copy()
            if machine_filter:
                filtered_df = filtered_df[filtered_df['Machine'].astype(str).str.contains(machine_filter, case=False, na=False)]
            if comp_filter:
                filtered_df = filtered_df[filtered_df['Component'].isin(comp_filter)]

            st.dataframe(filtered_df.tail(100), use_container_width=True)

            st.divider()
            st.caption(
                "For Snowflake Cortex Analyst chat (copied / missing entries, duplicates, turnaround), "
                "use the **Snowflake Intake** tab."
            )
            if st.button("Sync filtered Tiger rows to Snowflake now", use_container_width=True):
                try:
                    # Align Tiger column names to OCR frame shape expected by the mapper
                    sync_df = filtered_df.rename(columns={c: c for c in filtered_df.columns})
                    needed = list(OCR_TO_SF.keys())
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

# ---------- Snowflake Sample Intake (dashboard + Cortex Analyst chatbot) ----------
with tab3:
    st.subheader("MRG Laboratories — Sample Intake")
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

    try:
        # Manual CSV upload into Snowflake (same as original Sample Intake)
        with st.expander("Upload weekly OCR output CSV"):
            f = st.file_uploader("CSV", type="csv", label_visibility="collapsed", key="sf_csv_upload")
            if f is not None and st.button("Load into Snowflake"):
                up_df = pd.read_csv(f, dtype=str)
                up_df.columns = [c.strip().upper().replace(" ", "_") for c in up_df.columns]
                up_df = up_df.reindex(
                    columns=CSV_COLS + (["TUBE_SIZE"] if "TUBE_SIZE" in up_df.columns else [])
                )
                if "TUBE_SIZE" not in up_df.columns:
                    up_df["TUBE_SIZE"] = None
                batch = f"BATCH_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
                up_df["BATCH_ID"] = batch
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
                st.session_state.last_snowflake_batch = batch
                st.success(f"Loaded {len(up_df)} rows into batch {batch}")

        batches = sf_query(
            session, f"SELECT DISTINCT BATCH_ID FROM {DB_SCHEMA}.STAGING_SAMPLES ORDER BY 1 DESC"
        )["BATCH_ID"].tolist()

        if not batches:
            st.info("No pending samples in Snowflake yet. Process labels on the Image Upload tab first.")
        else:
            default_idx = 0
            if st.session_state.last_snowflake_batch in batches:
                default_idx = batches.index(st.session_state.last_snowflake_batch)
            batch = st.selectbox("Batch", batches, index=default_idx)

            data = sf_query(
                session,
                f"SELECT * FROM {DB_SCHEMA}.MRG_VIEW WHERE BATCH_ID = ?",
                [batch],
            )
            pending = data[data["STATUS"] == "PENDING"] if "STATUS" in data.columns else data
            dup_rows = pending[pending["IS_DUPLICATE"]] if "IS_DUPLICATE" in pending.columns else pending.iloc[0:0]

            c = st.columns(5)
            c[0].metric("Samples", len(data))
            c[1].metric("Duplicate IDs", int(data["IS_DUPLICATE"].sum()) if "IS_DUPLICATE" in data else 0)
            c[2].metric("Missing fields", int(data["HAS_MISSING_FIELD"].sum()) if "HAS_MISSING_FIELD" in data else 0)
            c[3].metric("Bad dates", int(data["HAS_BAD_DATE"].sum()) if "HAS_BAD_DATE" in data else 0)
            turnaround = (
                round(float(data["TURNAROUND_DAYS"].mean() or 0), 1)
                if "TURNAROUND_DAYS" in data and len(data)
                else 0
            )
            c[4].metric("Avg turnaround (days)", turnaround)

            if len(dup_rows):
                st.warning(
                    f"{len(dup_rows)} rows share a Sample ID and are flagged — see the Flagged samples tab."
                )

            tab_dash, tab_chat, tab_fix, tab_data = st.tabs(
                ["Dashboard", "Ask the data", "Flagged samples", "Data"]
            )

            with tab_dash:
                a, b = st.columns(2)
                if "DATE_RECEIVED" in data.columns:
                    a.subheader("Samples received per day")
                    a.bar_chart(data.groupby("DATE_RECEIVED").size().rename("samples"))
                if "MACHINE" in data.columns:
                    b.subheader("Samples per machine")
                    b.bar_chart(data.groupby("MACHINE").size().rename("samples"))
                if "COMPONENT" in data.columns:
                    a.subheader("Samples per component")
                    a.bar_chart(data.groupby("COMPONENT").size().rename("samples"))
                if "TUBE_SIZE" in data.columns:
                    b.subheader("Small vs Large tubes")
                    b.bar_chart(data.groupby("TUBE_SIZE").size().rename("samples"))

            with tab_chat:
                st.caption(
                    "Ask a question, e.g. 'Which machines have the longest turnaround?' "
                    "or 'Which Sample IDs are missing fields?'"
                )
                for m in st.session_state.msgs:
                    with st.chat_message(m["role"]):
                        for part in m["content"]:
                            if part["type"] == "text":
                                st.markdown(part["text"])
                            elif part["type"] == "sql":
                                with st.expander("SQL"):
                                    st.code(part["statement"], language="sql")
                                res = sf_query(session, part["statement"])
                                st.dataframe(res, use_container_width=True)
                                num = res.select_dtypes("number").columns
                                if len(res.columns) == 2 and len(num) == 1 and len(res) > 1:
                                    st.bar_chart(res.set_index(res.columns[0]))

                prompt = st.chat_input("Ask Cortex Analyst about this intake data…")
                if prompt:
                    st.session_state.msgs.append(
                        {"role": "user", "content": [{"type": "text", "text": prompt}]}
                    )
                    try:
                        reply = ask_analyst(session, st.session_state.msgs)
                        st.session_state.msgs.append(
                            {"role": "analyst", "content": reply["content"]}
                        )
                    except Exception as e:
                        st.session_state.msgs.pop()
                        st.error(str(e))
                    st.rerun()

            flagged = pending.copy()
            if len(flagged) and {"IS_DUPLICATE", "HAS_MISSING_FIELD", "HAS_BAD_DATE"}.issubset(flagged.columns):
                flagged = flagged[
                    flagged["IS_DUPLICATE"] | flagged["HAS_MISSING_FIELD"] | flagged["HAS_BAD_DATE"]
                ].copy()
                flagged["FLAG_REASON"] = [
                    ", ".join(
                        n for n, flag in [
                            ("Duplicate ID", d),
                            ("Missing field", m),
                            ("Bad date", b),
                        ] if flag
                    )
                    for d, m, b in zip(
                        flagged["IS_DUPLICATE"],
                        flagged["HAS_MISSING_FIELD"],
                        flagged["HAS_BAD_DATE"],
                    )
                ]
            else:
                flagged = flagged.iloc[0:0]

            with tab_flag:
                if len(flagged):
                    unflagged_col = "UNFLAGGED" if "UNFLAGGED" in flagged.columns else None
                    if unflagged_col:
                        st.warning(
                            f"{int((~flagged['UNFLAGGED']).sum())} samples are flagged. "
                            "Labels can't be corrected — they will be submitted with their flag."
                        )
                        st.caption("Tick 'Unflag' to clear a flag (untick to re-flag), then save.")
                        edited = st.data_editor(
                            flagged[["UNFLAGGED", "FLAG_REASON", "ROW_ID"] + CSV_COLS + ["TUBE_SIZE"]],
                            key="unflag_editor",
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "UNFLAGGED": st.column_config.CheckboxColumn("Unflag"),
                                "ROW_ID": None,
                            },
                            disabled=["FLAG_REASON"] + CSV_COLS + ["TUBE_SIZE"],
                        )
                        changed = edited[edited["UNFLAGGED"] != flagged["UNFLAGGED"].values]
                        if st.button("Save flag changes", disabled=changed.empty):
                            for row_id, val in zip(changed["ROW_ID"], changed["UNFLAGGED"]):
                                session.sql(
                                    f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES "
                                    f"SET UNFLAGGED = ? WHERE ROW_ID = ?",
                                    params=[bool(val), int(row_id)],
                                ).collect()
                            st.toast("Flag changes saved.")
                            st.rerun()
                    else:
                        st.dataframe(flagged, use_container_width=True, hide_index=True)
                else:
                    st.success("No flagged samples — ready to submit.")

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
                    SELECT SAMPLE_ID, DATE_SAMPLED, DATE_RECEIVED, MACHINE, COMPONENT, SERIAL_NUMBER, REFERENCE_LUBE,
                           TUBE_SIZE, BATCH_ID, CURRENT_TIMESTAMP(), ?,
                           IS_FLAGGED,
                           NULLIF(ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(
                               IFF(IS_DUPLICATE, 'Duplicate ID', NULL),
                               IFF(HAS_MISSING_FIELD, 'Missing field', NULL),
                               IFF(HAS_BAD_DATE, 'Bad date', NULL),
                               IFF(UNFLAGGED AND (IS_DUPLICATE OR HAS_MISSING_FIELD OR HAS_BAD_DATE), '(unflagged by user)', NULL)), ', '), '')
                    FROM {DB_SCHEMA}.MRG_VIEW WHERE BATCH_ID = ? AND STATUS = 'PENDING'
                    """,
                    params=[user, batch],
                ).collect()
                session.sql(
                    f"UPDATE {DB_SCHEMA}.STAGING_SAMPLES SET STATUS = 'SUBMITTED' "
                    f"WHERE BATCH_ID = ? AND STATUS = 'PENDING'",
                    params=[batch],
                ).collect()
                session.sql(
                    f"INSERT INTO {DB_SCHEMA}.SUBMISSION_LOG VALUES (?, CURRENT_TIMESTAMP(), ?, ?, ?)",
                    params=[batch, user, n, action],
                ).collect()
                st.session_state.popup = (
                    f"Your data has been submitted to MRG: {n} samples "
                    f"({flagged_count} flagged for review)."
                )

            @st.dialog("Submitted to MRG")
            def submitted_popup(msg: str):
                st.success(msg)
                if st.button("OK"):
                    st.rerun()

            if st.button("Submit to MRG", type="primary", disabled=nothing, use_container_width=True):
                submit("SUBMIT")
                st.rerun()
            if nothing:
                st.caption("No pending samples in this batch.")
            if "popup" in st.session_state:
                submitted_popup(st.session_state.pop("popup"))

    except Exception as e:
        st.error(f"Snowflake Intake error: {e}")
    finally:
        try:
            session.close()
        except Exception:
            pass

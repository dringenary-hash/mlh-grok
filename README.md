# MRG Labs — Sample Label Scanner (YCP Hacks)

Streamlit app for the Schneider Prize for Technology Innovation flow:

1. **OCR** label images with Gemini  
2. **Write CSV/rows to Tiger Data**  
3. **Sync the same batch to Snowflake** (`MRG_LABS_DB.INTAKE.STAGING_SAMPLES`)  
4. **Auto-run Grok QC** on the batch (SpaceXSI automation)  
5. **Review + chat** with Snowflake Cortex Analyst on the **Snowflake Intake** tab  

## Tabs

- **Image Upload** — Gemini OCR, Tiger Data write, Snowflake sync, **Grok auto-QC**, CSV download  
- **Data Viewer** — live Tiger Data table + optional re-sync to Snowflake  
- **Snowflake Intake** — Sample Intake dashboard, flagged samples, Cortex Analyst chatbot, submit to MRG  

## Grok / SpaceXSI

See **[GROK_AUTOMATION.md](GROK_AUTOMATION.md)** for how we use Cursor + Grok automation, what `XAI_API_KEY` is for, and submission talking points. Run history lands in `grok_qc_log.md`.

## Required environment

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini OCR |
| `TIGERDATA_URI` | Tiger Data (Postgres) SQLAlchemy URI |
| `XAI_API_KEY` | Grok auto-QC (`GROK_API_KEY` also accepted) |
| `GROK_MODEL` | optional, default `grok-3-mini` |
| `SNOWFLAKE_ACCOUNT` | Snowflake account |
| `SNOWFLAKE_USER` | Snowflake user |
| `SNOWFLAKE_PRIVATE_KEY_PATH` | Path to `rsa_key.p8` (default: `rsa_key.p8`) |
| `SNOWFLAKE_DATABASE` | Default `MRG_LABS_DB` |
| `SNOWFLAKE_SCHEMA` | Default `INTAKE` |
| `SNOWFLAKE_WAREHOUSE` | Default `COMPUTE_WH` |
| `SNOWFLAKE_ROLE` | Default `ACCOUNTADMIN` |

Snowflake objects expected (from the Sample Intake demo): `STAGING_SAMPLES`, `MRG_VIEW`, `MRG_SAMPLES`, `SUBMISSION_LOG`, semantic view `MRG_INTAKE_SV`.

## Run

```bash
export XAI_API_KEY="your_xai_key"
streamlit run app.py
```

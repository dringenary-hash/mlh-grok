# MRG Labs — Sample Label Scanner (YCP Hacks)

Merged Streamlit app for Schneider / Tiger Data / Snowflake:

1. **OCR** label images with Gemini  
2. **Write** rows to **Tiger Data**  
3. **Sync** the same batch to Snowflake `MRG_LABS_DB.INTAKE.STAGING_SAMPLES`  
4. **Review + chat** on the **Snowflake Intake** tab (updated Sample Intake / Cortex Analyst)

## Tabs

- **Image Upload** — Gemini OCR, Tiger Data write, Snowflake sync, CSV download, minesweeper  
- **Data Viewer** — live Tiger Data table + optional re-sync to Snowflake  
- **Snowflake Intake** — server feed, all-batches view, dashboard, Cortex Analyst chat, flags, submit to MRG  

`MRG_Laboratories_Sample_Intake.py` is the standalone Sample Intake reference (app2).

## Env

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini OCR |
| `TIGERDATA_URI` | Tiger Data (Postgres) SQLAlchemy URI |
| `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` | Snowflake key-pair login |
| `rsa_key.p8` | Private key (or `SNOWFLAKE_PRIVATE_KEY_PATH`) |
| `SNOWFLAKE_DATABASE` / `SCHEMA` / `WAREHOUSE` / `ROLE` | optional overrides |

## Run

```bash
streamlit run app.py
```

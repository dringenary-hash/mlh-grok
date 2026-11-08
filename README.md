# MRG Labs — Sample Intake (Snowflake)

Streamlit dashboard + Cortex Analyst chatbot for the Schneider Prize 2026 demo.

## Run

```bash
streamlit run app.py
```

Expects Snowflake objects under `MRG_LABS_DB.INTAKE` (including `STAGING_SAMPLES`, `MRG_VIEW`, `MRG_SAMPLES`, `SUBMISSION_LOG`, `MRG_INTAKE_SV`, and the feed helpers).

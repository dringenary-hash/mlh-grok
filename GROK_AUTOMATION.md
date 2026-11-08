# Grok Automation — SpaceXSI / MLH Documentation

This project uses **Cursor** as the core AI coding agent and **Grok (xAI)** as an automated QC step in the sample-intake pipeline.

## What the API key is for

`XAI_API_KEY` (alias: `GROK_API_KEY`) authenticates HTTPS calls to xAI’s Chat Completions API:

- **Endpoint:** `POST https://api.x.ai/v1/chat/completions`
- **Model:** `GROK_MODEL` env var (default `grok-3-mini`)
- **Purpose:** After Gemini OCR writes to **Tiger Data** and syncs to **Snowflake**, Grok automatically reviews batch stats and returns a short readiness report (missing fields, duplicate Sample IDs, OCR failures, READY TO SUBMIT vs NEEDS REVIEW).

The key is **not** used for OCR (Gemini) or the Snowflake Cortex Analyst chatbot. It is only for this Grok QC automation.

## Automation flow

1. User uploads label images → **Gemini OCR**
2. Rows append to **Tiger Data** (`lab_samples`)
3. Same batch syncs to **Snowflake** `MRG_LABS_DB.INTAKE.STAGING_SAMPLES`
4. **Grok auto-runs** (no button): app sends batch statistics JSON to Grok
5. Grok reply is shown under **“Grok Automation — Batch QC”** on the Image Upload tab
6. The same report is appended to `grok_qc_log.md` as submission evidence

## How to enable

```bash
export XAI_API_KEY="your_xai_key"
# optional:
export GROK_MODEL="grok-3-mini"
export GROK_QC_LOG="grok_qc_log.md"

streamlit run app.py
```

## Demo talking points (Devpost / judges)

- **Cursor:** built and iterated the OCR → Tiger Data → Snowflake → Grok pipeline
- **Grok Bot automation:** every processed batch is auto-QC’d by Grok before human review / Snowflake Intake chat
- **Evidence:** live UI panel + `grok_qc_log.md` run history

## Related files

| File | Role |
|---|---|
| `app.py` | `run_grok_batch_qc()` + auto-run after Process All Labels |
| `grok_qc_log.md` | Append-only log of Grok QC runs |
| `GROK_AUTOMATION.md` | This document |

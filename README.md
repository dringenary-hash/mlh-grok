# MRG Labs — Sample Label Scanner (YCP Hacks)

1. **OCR** label images with Gemini (Large vs Small tube)
2. **Anchor** each sample on Solana devnet
3. **Write** rows to **Tiger Data**
4. **Sync** the batch to Snowflake `MRG_LABS_DB.INTAKE.STAGING_SAMPLES`
5. **Auto-run Grok QC** (SpaceXSI) — see [GROK_AUTOMATION.md](GROK_AUTOMATION.md)
6. **Grease Intelligence** tab — local dashboard, grid edits, Gemini reasoning
7. **Snowflake Intake** tab — Sample Intake app (server feed, Cortex Analyst, flags, submit to MRG)

## Env

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | OCR + grease reasoning |
| `TIGERDATA_URI` | Tiger Data |
| `XAI_API_KEY` | Grok auto-QC (`.env`, gitignored) |
| `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` | Key-pair login |
| `rsa_key.p8` | Snowflake private key |
| `SOLANA_SECRET_KEY` | Devnet memo anchor |

```bash
streamlit run app.py
```

`MRG_Laboratories_Sample_Intake.py` is the standalone Sample Intake reference.

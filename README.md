# MRG Labs — Sample Label Scanner (YCP Hacks)

Updated scanner (`new_py`) plus Grok auto-QC.

1. **OCR** label images with Gemini (Large vs Small tube)
2. **Anchor** each sample on Solana devnet
3. **Write** rows to **Tiger Data**
4. **Sync** the batch to Snowflake
5. **Auto-run Grok QC** after each batch (SpaceXSI) — see [GROK_AUTOMATION.md](GROK_AUTOMATION.md)
6. **Snowflake Intake** tab — grease dashboard, grid edits, and reasoning chat

## Env

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | OCR + reasoning chat |
| `TIGERDATA_URI` | Tiger Data |
| `XAI_API_KEY` | Grok auto-QC (`.env`, gitignored) |
| `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` | Key-pair login |
| `rsa_key.p8` | Snowflake private key |
| `SOLANA_SECRET_KEY` | Devnet memo anchor |

```bash
streamlit run app.py
```

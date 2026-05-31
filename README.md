# Text-to-SQL: Natural Language Database Querying

Ask questions about your data in plain English. Get SQL. Get answers.

This is a fully functional web app that lets anyone — technical or not — upload a CSV or Excel file and query it using natural language, powered by Groq's LLaMA 3.3 70B model and a dynamic SQL validation pipeline.

---

## What It Does

1. **Upload** any CSV or Excel file (multi-sheet Excel supported)
2. **Ask** a question in plain English — *"How many rows per category?"* or *"Show me the top 10 by sales"*
3. **Get** the generated SQL, validated results, and a downloadable CSV — instantly

No database setup. No SQL knowledge required.

---

## How It Works

```
User Question → Groq LLaMA 3.3 → Raw SQL → Validator → SQLite (in-memory) → Results
```

- **Dynamic schema detection** — the app reads column names and types from whatever file you upload and builds the LLM prompt automatically
- **SQL validator** — blocks dangerous keywords (DROP, DELETE, INSERT) and verifies all tokens against the actual schema before execution
- **Auto-fix loop** — if generated SQL fails validation, the app sends the error back to the LLM and retries automatically
- **In-memory SQLite** — data lives in RAM only, never written to disk

---

## Features

- CSV and multi-sheet Excel support
- Schema preview + 5-row data preview before querying
- Sample questions auto-generated from your actual column names
- SQL displayed before execution so you can see exactly what ran
- Results downloadable as CSV
- File size limit enforced (5MB)

---

## Demo

| Question | Generated SQL |
|----------|--------------|
| How many rows are there? | `SELECT COUNT(*) AS total FROM table;` |
| Show distinct values in Class | `SELECT DISTINCT Class FROM table;` |
| How many students per section? | `SELECT Section, COUNT(*) AS total FROM table GROUP BY Section;` |

---

## Setup

```bash
git clone https://github.com/MadhuDamani12/Text-to-SQL-App
cd Text-to-SQL-App
pip install -r requirements.txt
```

Create a `.env` file with your Groq API key:
```
GROQ_API_KEY=your_key_here
```

Run the app:
```bash
# Optional: seed the sample database
python sql.py

# Launch the app
streamlit run app.py
```

---

## Files

| File | Description |
|------|-------------|
| `app.py` | Main Streamlit app — file upload, schema detection, LLM integration, SQL validation, results display |
| `sql.py` | Script to create and seed a sample SQLite database for testing |
| `requirements.txt` | Python dependencies |

---

## Tools

Python · Streamlit · Groq (LLaMA 3.3 70B) · SQLite · Pandas · LangChain · python-dotenv

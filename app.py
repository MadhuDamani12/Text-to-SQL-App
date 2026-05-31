from dotenv import load_dotenv
load_dotenv()

import os
import re
import sqlite3

import streamlit as st
import pandas as pd
from groq import Groq

# ──────────────────────────────────────────────
# Groq client
# ──────────────────────────────────────────────
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"

# ──────────────────────────────────────────────
# SQL keywords the validator always accepts
# ──────────────────────────────────────────────
SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "LIMIT", "COUNT", "DISTINCT",
    "ORDER", "BY", "ASC", "DESC", "GROUP", "HAVING",
    "AND", "OR", "NOT", "IN", "LIKE", "IS", "NULL",
    "AS", "ALL", "TOP", "AVG", "SUM", "MIN", "MAX",
    "BETWEEN", "CASE", "WHEN", "THEN", "ELSE", "END",
    "*", "1", "10",
}

# ──────────────────────────────────────────────
# NEW: File loading functions
# ──────────────────────────────────────────────

def load_file(uploaded_file):
    """
    Reads a CSV or Excel file uploaded by the user.

    Returns:
        df         : pandas DataFrame of the selected data
        table_name : what we'll call this table in SQLite
        sheet_name : None for CSV, or the chosen sheet name for Excel
        all_sheets : None for CSV, or list of all sheet names for Excel
    """
    name = uploaded_file.name

    # ── CSV ───────────────────────────────────
    if name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)

        # Table name = filename without .csv, spaces replaced with underscores
        # e.g. "my students.csv" → "my_students"
        table_name = name.replace(".csv", "").replace(" ", "_")

        return df, table_name, None, None

    # ── Excel ─────────────────────────────────
    elif name.endswith(".xlsx"):
        # pd.ExcelFile lets us peek at sheet names without loading all data
        xl = pd.ExcelFile(uploaded_file)
        all_sheets = xl.sheet_names  # e.g. ["Students", "Teachers", "Courses"]

        # We return the sheet list here and let the UI handle the dropdown
        # The actual df will be loaded after the user picks a sheet
        return None, None, None, all_sheets

    else:
        return None, None, None, None


def load_excel_sheet(uploaded_file, sheet_name):
    """
    Loads one specific sheet from an Excel file into a DataFrame.
    Called after the user picks a sheet from the dropdown.
    """
    df = pd.read_excel(uploaded_file, sheet_name=sheet_name)

    # Table name = chosen sheet name, spaces → underscores
    # e.g. "My Students" → "My_Students"
    table_name = sheet_name.replace(" ", "_")

    return df, table_name


def build_database(df, table_name):
    """
    Takes a pandas DataFrame and loads it into an in-memory SQLite database.

    ":memory:" means the database lives in RAM only.
    It disappears when the session ends — perfect for a web app.

    Returns the connection object so we can run queries against it later.
    """
    # Create a fresh in-memory database
    conn = sqlite3.connect(":memory:")

    # Write the DataFrame as a table
    # if_exists="replace" means if a table with this name exists, overwrite it
    # index=False means don't write the DataFrame row numbers as a column
    df.to_sql(table_name, conn, if_exists="replace", index=False)

    return conn


def get_schema(conn, table_name):
    """
    Reads column names and their types from SQLite.

    PRAGMA table_info() is a special SQLite command that returns metadata
    about a table. Each row contains:
      row[0] = column index
      row[1] = column name   ← we want this
      row[2] = column type   ← we want this too (TEXT, INTEGER, REAL etc.)
      ...

    Returns a list of (column_name, column_type) tuples.
    e.g. [("NAME", "TEXT"), ("AGE", "INTEGER"), ("SALARY", "REAL")]
    """
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info('{table_name}')")
    rows = cursor.fetchall()
    return [(row[1], row[2]) for row in rows]


def build_prompt(table_name, schema):
    """
    Builds the Groq system prompt dynamically using the actual
    table name and columns from whatever the user uploaded.

    This replaces the hardcoded SYSTEM_PROMPT from v1.

    schema is a list of (col_name, col_type) tuples.
    e.g. [("NAME", "TEXT"), ("AGE", "INTEGER")]
    """
    # Build a readable columns string: "NAME (TEXT), AGE (INTEGER), SALARY (REAL)"
    columns_str = ", ".join(f"{col} ({dtype})" for col, dtype in schema)

    # Column names only (for the rules section)
    col_names_only = ", ".join(col for col, _ in schema)

    return f"""
You are a strict SQL generator for a SQLite database.

Schema:
  Table  : {table_name}
  Columns: {columns_str}

Rules:
1. Return ONLY a raw SQL SELECT statement — no explanation, no markdown, no backticks.
2. Use ONLY the columns listed above: {col_names_only}
   If the user asks for a column that does not exist, return:
       SELECT 'ERROR: Column not found' AS message;
3. Always add LIMIT 10 unless the user asks for all records or a count/aggregate.
4. Use LIKE for partial or case-insensitive text matches when appropriate.
5. Never use INSERT, UPDATE, DELETE, DROP, or any DDL/DML other than SELECT.

Examples (using your actual table and columns):
Q: How many rows are there?
A: SELECT COUNT(*) AS total FROM {table_name};

Q: Show first 10 rows
A: SELECT * FROM {table_name} LIMIT 10;

Q: Show distinct values in a column (replace COLUMN with actual column name)
A: SELECT DISTINCT COLUMN FROM {table_name};

Q: How many records per group (replace COL with actual column name)
A: SELECT COL, COUNT(*) AS total FROM {table_name} GROUP BY COL;
"""


# ──────────────────────────────────────────────
# SQL helpers
# ──────────────────────────────────────────────

def clean_sql(raw: str) -> str:
    """Strip markdown fences without corrupting SQL content."""
    raw = re.sub(r"```[\w]*", "", raw, flags=re.IGNORECASE)
    raw = raw.strip().strip("`").strip()
    parts = [s.strip() for s in raw.split(";") if s.strip()]
    return (parts[0] + ";") if parts else raw


def is_valid_sql(sql: str, valid_columns: set, table_name: str) -> tuple[bool, str]:
    """
    Same logic as v1 but now receives valid_columns and table_name
    as arguments instead of reading global constants.

    This is the key change — validator is now dynamic.
    """
    upper = sql.upper().strip()

    if not upper.startswith("SELECT"):
        return False, "Query must start with SELECT."

    dangerous = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                 "TRUNCATE", "CREATE", "REPLACE", "EXEC"}
    for kw in dangerous:
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Blocked keyword detected: {kw}"

    # Strip string literals so 'Data Science' doesn't produce unknown tokens
    no_strings = re.sub(r"'[^']*'", "''", upper)
    tokens = re.split(r"[\s,();]+", no_strings)

    for token in tokens:
        token = token.strip()
        if not token or token in ("''", ";", ""):
            continue
        if re.fullmatch(r"-?\d+(\.\d+)?", token):
            continue
        if token in {"=", "<", ">", "<=", ">=", "!=", "<>",
                     "*", "%", "+", "-", "/"}:
            continue
        if token in SQL_KEYWORDS:
            continue
        if token in valid_columns:        # ← uses dynamic columns now
            continue
        if token == table_name.upper():   # ← uses dynamic table name now
            continue
        return False, f"Unknown token: '{token}'"

    return True, ""


def generate_sql(question: str, system_prompt: str) -> str:
    """Call Groq and return cleaned SQL. (unchanged from v1)"""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.0,
            max_tokens=150,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": question},
            ],
        )
        raw = resp.choices[0].message.content or ""
        return clean_sql(raw)
    except Exception as e:
        return f"ERROR: {e}"


def run_query(sql: str, conn) -> tuple[list | None, list | str]:
    """
    Execute SQL against the in-memory connection.

    Changed from v1: now receives the connection as an argument
    instead of opening a file path. Everything else is identical.
    """
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows      = cur.fetchall()
        col_names = [d[0] for d in cur.description] if cur.description else []
        return col_names, rows
    except Exception as e:
        return None, f"SQL execution error: {e}"


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────
st.set_page_config(page_title="Text to SQL — Dynamic", layout="centered")

st.title("🗄️ Text to SQL")
st.caption("Upload any CSV or Excel file and ask questions in plain English.")

# ── STEP 1: File upload ───────────────────────
st.subheader("1. Upload your file")

uploaded_file = st.file_uploader(
    "Choose a CSV or Excel file",
    type=["csv", "xlsx"],           # only accept these formats
    help="Max file size: 5MB"
)

# Nothing else runs until a file is uploaded
if uploaded_file is None:
    st.info("Upload a CSV or Excel file above to get started.")
    st.stop()  # halt script here — don't render anything below

# ── STEP 2: Size check ────────────────────────
MAX_SIZE = 5 * 1024 * 1024  # 5MB in bytes
if uploaded_file.size > MAX_SIZE:
    st.error("File is too large. Please upload a file under 5MB.")
    st.stop()

# ── STEP 3: Load file + handle Excel sheets ──
# We use st.session_state to remember the connection and schema
# across reruns (Streamlit reruns the whole script on every interaction)

# Check if this is a NEW file upload (different from what we already loaded)
# uploaded_file.name gives us the filename to compare
current_file = st.session_state.get("loaded_file_name")
current_sheet = st.session_state.get("loaded_sheet")

if uploaded_file.name.endswith(".xlsx"):
    # Peek at sheet names first
    xl        = pd.ExcelFile(uploaded_file)
    all_sheets = xl.sheet_names

    if len(all_sheets) > 1:
        # Show dropdown only when there are multiple sheets
        selected_sheet = st.selectbox(
            "This Excel file has multiple sheets. Which one do you want to query?",
            all_sheets
        )
    else:
        # Single sheet — no dropdown needed
        selected_sheet = all_sheets[0]

    # Reload only if file or sheet changed
    if uploaded_file.name != current_file or selected_sheet != current_sheet:
        df, table_name = load_excel_sheet(uploaded_file, selected_sheet)
        conn           = build_database(df, table_name)
        schema         = get_schema(conn, table_name)

        # Save everything into session_state so it survives reruns
        st.session_state["conn"]             = conn
        st.session_state["table_name"]       = table_name
        st.session_state["schema"]           = schema
        st.session_state["loaded_file_name"] = uploaded_file.name
        st.session_state["loaded_sheet"]     = selected_sheet
        st.session_state["df_preview"]       = df

else:
    # CSV — no sheet selection needed
    if uploaded_file.name != current_file:
        df, table_name, _, _ = load_file(uploaded_file)
        conn                  = build_database(df, table_name)
        schema                = get_schema(conn, table_name)

        st.session_state["conn"]             = conn
        st.session_state["table_name"]       = table_name
        st.session_state["schema"]           = schema
        st.session_state["loaded_file_name"] = uploaded_file.name
        st.session_state["loaded_sheet"]     = None
        st.session_state["df_preview"]       = df

# Retrieve from session_state for use below
conn       = st.session_state["conn"]
table_name = st.session_state["table_name"]
schema     = st.session_state["schema"]
df_preview = st.session_state["df_preview"]

# Build dynamic sets for validator
# {col.upper() for col, _ in schema} → {"NAME", "CLASS", "SECTION"}
valid_columns = {col.upper() for col, _ in schema}

# Build dynamic system prompt
system_prompt = build_prompt(table_name, schema)

# ── STEP 4: Show schema to user ───────────────
st.subheader("2. Understand your data")

# Two columns side by side: schema on left, preview on right
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Detected schema**")
    # Show each column as a small badge-style row
    for col_name, col_type in schema:
        st.markdown(
            f"`{col_name}` &nbsp; "
            f"<span style='color:gray;font-size:12px'>{col_type}</span>",
            unsafe_allow_html=True
        )

with col_right:
    st.markdown("**Data preview (first 5 rows)**")
    st.dataframe(df_preview.head(5), use_container_width=True, hide_index=True)

# ── STEP 5: Sample questions ──────────────────
st.subheader("3. Ask a question")

with st.expander("Need inspiration? Try these"):
    examples = [
        f"How many rows are in the table?",
        f"Show me the first 10 rows",
        f"Show all distinct values in {schema[0][0] if schema else 'column'}",
        f"How many records are there per {schema[1][0] if len(schema) > 1 else 'group'}?",
    ]
    for ex in examples:
        if st.button(ex, key=ex):
            st.session_state["question_input"] = ex

question = st.text_input(
    "Your question:",
    placeholder="e.g. How many rows are there?",
    key="question_input",
)
submit = st.button("Generate & Run SQL", type="primary")

# ──────────────────────────────────────────────
# Main query logic (same structure as v1)
# Only differences:
#   - system_prompt is dynamic (built above)
#   - is_valid_sql receives valid_columns and table_name
#   - run_query receives conn instead of a file path
# ──────────────────────────────────────────────
if submit:
    if not question.strip():
        st.warning("Please enter a question.")
        st.stop()

    # ── Generate ──────────────────────────────
    with st.spinner("Generating SQL with Groq..."):
        sql = generate_sql(question, system_prompt)

    if not sql or sql.startswith("ERROR:"):
        st.error(f"Failed to generate SQL: {sql}")
        st.stop()

    st.subheader("📄 Generated SQL")
    st.code(sql, language="sql")

    # ── Validate ──────────────────────────────
    valid, reason = is_valid_sql(sql, valid_columns, table_name)

    if not valid:
        st.warning(f"⚠️ Validation issue: {reason} — retrying…")

        fix_prompt = (
            f"The SQL you generated is invalid: {reason}\n"
            f"Original SQL: {sql}\n"
            f"Original question: {question}\n"
            f"Fix it. Use ONLY these columns: "
            f"{', '.join(col for col, _ in schema)} "
            f"from table {table_name}."
        )

        with st.spinner("Auto-fixing SQL…"):
            sql = generate_sql(fix_prompt, system_prompt)

        st.subheader("🔁 Fixed SQL")
        st.code(sql, language="sql")

        valid, reason = is_valid_sql(sql, valid_columns, table_name)
        if not valid:
            st.error(
                f"Still invalid after auto-fix ({reason}). "
                "Please rephrase your question."
            )
            st.stop()

    # ── Execute ───────────────────────────────
    col_names, result = run_query(sql, conn)

    st.subheader("📊 Results")

    if isinstance(result, str):
        st.error(result)

    elif len(result) == 0:
        st.info("Query ran successfully — no rows matched.")

    else:
        result_df = pd.DataFrame(result, columns=col_names)

        st.caption(f"{len(result_df)} row(s) returned")
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        csv_download = result_df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download results as CSV",
            data=csv_download,
            file_name="query_result.csv",
            mime="text/csv",
        )

import sqlite3
 
conn = sqlite3.connect("student.db")
cur = conn.cursor()
 
cur.execute("""
CREATE TABLE IF NOT EXISTS STUDENT (
    NAME    TEXT,
    CLASS   TEXT,
    SECTION TEXT
)
""")
 
# Sample data
students = [
    ("Alice Johnson",  "Data Science",     "A"),
    ("Bob Smith",      "Data Science",     "B"),
    ("Carol White",    "Machine Learning", "A"),
    ("David Lee",      "Data Science",     "A"),
    ("Eva Martinez",   "Machine Learning", "B"),
    ("Frank Brown",    "Cloud Computing",  "A"),
    ("Grace Kim",      "Cloud Computing",  "B"),
    ("Henry Davis",    "Data Science",     "C"),
    ("Isla Wilson",    "Machine Learning", "A"),
    ("Jack Taylor",    "Cloud Computing",  "C"),
]
 
cur.executemany("INSERT INTO STUDENT VALUES (?, ?, ?)", students)
 
conn.commit()
conn.close()
print("Done — student.db created with 10 sample rows (NAME, CLASS, SECTION).")
 








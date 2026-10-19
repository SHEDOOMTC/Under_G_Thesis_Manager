import sqlite3
from werkzeug.security import generate_password_hash

students = [
    ('2023001', 'student123', 'Student One', 'student1@example.com'),
    ('2023002', 'student456', 'Student Two', 'student2@example.com'),
]

conn = sqlite3.connect('instance/thesis.db')
cur = conn.cursor()
cur.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    full_name TEXT,
    email TEXT,
    can_edit_thesis INTEGER NOT NULL DEFAULT 0
)
''')

for username, password, full_name, email in students:
    existing = cur.execute(
        'SELECT 1 FROM users WHERE username = ? AND role = ?',
        (username, 'student')
    ).fetchone()

    if existing is None:
        cur.execute(
            'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, 0)',
            (username, generate_password_hash(password), 'student', full_name, email),
        )
    else:
        cur.execute(
            'UPDATE users SET password_hash = ?, full_name = ?, email = ? WHERE username = ? AND role = ?',
            (generate_password_hash(password), full_name, email, username, 'student'),
        )

conn.commit()
print('student accounts seeded')
for row in cur.execute("SELECT username, role, full_name, email FROM users WHERE role='student' ORDER BY id"):
    print(row)
conn.close()

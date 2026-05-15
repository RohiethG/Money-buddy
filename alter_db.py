import sqlite3

conn = sqlite3.connect('database.db')  # Make sure this matches your DB file name
c = conn.cursor()

try:
    c.execute("ALTER TABLE expenses ADD COLUMN category TEXT")
    print("✅ 'category' column added successfully.")
except sqlite3.OperationalError as e:
    print("⚠️ Column may already exist or another error occurred:", e)

conn.commit()
conn.close()

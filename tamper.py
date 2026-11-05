import sqlite3

conn = sqlite3.connect("data/nexusbank.db")

# Show BEFORE
print("=== BEFORE TAMPER ===")
rows = conn.execute("SELECT tx_id, status, amount FROM transactions").fetchall()
for r in rows:
    print(r)

# Tamper the amount
conn.execute("UPDATE transactions SET amount=1000 WHERE tx_id='TXN-7R4NOYHUZS'")
conn.commit()

# Show AFTER
print("\n=== AFTER TAMPER ===")
rows = conn.execute("SELECT tx_id, status, amount FROM transactions").fetchall()
for r in rows:
    print(r)

conn.close()
print("\nDone! Now go verify TXN-7R4NOYHUZS in the browser.")

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import date, datetime

app = Flask(__name__)
CORS(app)

DB_PATH = "database.db"

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        monthly_budget REAL
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        category TEXT,
        date TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bills (
        bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        bill_name TEXT,
        amount REAL,
        due_date TEXT,
        status TEXT DEFAULT 'Pending',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")
    conn.commit()
    conn.close()

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    budget   = data.get("budget", 0)
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    try:
        conn = connect_db()
        conn.execute(
            "INSERT INTO users(username,password,monthly_budget) VALUES(?,?,?)",
            (username, password, float(budget))
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Registered successfully"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 409

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    conn = connect_db()
    row = conn.execute(
        "SELECT id, username, monthly_budget FROM users WHERE username=? AND password=?",
        (data["username"], data["password"])
    ).fetchone()
    conn.close()
    if row:
        return jsonify({"user_id": row["id"], "username": row["username"], "budget": row["monthly_budget"]})
    return jsonify({"error": "Invalid credentials"}), 401

# ── Transactions ──────────────────────────────────────────────────────────────

@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    user_id = request.args.get("user_id")
    conn = connect_db()
    rows = conn.execute(
        "SELECT id, type, amount, category, date FROM transactions WHERE user_id=? ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/transactions", methods=["POST"])
def add_transaction():
    data = request.json
    d = data.get("date") or str(date.today())
    conn = connect_db()
    conn.execute(
        "INSERT INTO transactions(user_id,type,amount,category,date) VALUES(?,?,?,?,?)",
        (data["user_id"], data["type"], float(data["amount"]), data["category"], d)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Transaction added"})

@app.route("/api/transactions/<int:txn_id>", methods=["DELETE"])
def delete_transaction(txn_id):
    conn = connect_db()
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})

# ── Summary ───────────────────────────────────────────────────────────────────

@app.route("/api/summary", methods=["GET"])
def summary():
    user_id = request.args.get("user_id")
    conn = connect_db()
    income  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='income'",  (user_id,)).fetchone()[0]
    expense = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='expense'", (user_id,)).fetchone()[0]
    budget  = conn.execute("SELECT monthly_budget FROM users WHERE id=?", (user_id,)).fetchone()[0]
    conn.close()
    pct = round((expense / budget * 100), 1) if budget else 0
    alert = "Budget exceeded!" if pct > 100 else ("80% budget used" if pct > 80 else "Budget safe")
    return jsonify({
        "income": income, "expense": expense,
        "balance": income - expense,
        "budget": budget, "budget_pct": pct, "alert": alert
    })

# ── Bills ─────────────────────────────────────────────────────────────────────

@app.route("/api/bills", methods=["GET"])
def get_bills():
    user_id = request.args.get("user_id")
    conn = connect_db()
    rows = conn.execute(
        "SELECT bill_id, bill_name, amount, due_date, status FROM bills WHERE user_id=? ORDER BY due_date",
        (user_id,)
    ).fetchall()
    conn.close()
    today = datetime.today()
    result = []
    for r in rows:
        b = dict(r)
        try:
            due = datetime.strptime(b["due_date"], "%Y-%m-%d")
            if b["status"] == "Pending" and due < today:
                b["display_status"] = "OVERDUE"
            else:
                b["display_status"] = b["status"]
        except:
            b["display_status"] = b["status"]
        result.append(b)
    return jsonify(result)

@app.route("/api/bills", methods=["POST"])
def add_bill():
    data = request.json
    conn = connect_db()
    conn.execute(
        "INSERT INTO bills(user_id,bill_name,amount,due_date,status) VALUES(?,?,?,?,'Pending')",
        (data["user_id"], data["bill_name"], float(data["amount"]), data["due_date"])
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Bill added"})

@app.route("/api/bills/<int:bill_id>", methods=["PUT"])
def update_bill(bill_id):
    data = request.json
    conn = connect_db()
    conn.execute("UPDATE bills SET status=? WHERE bill_id=?", (data["status"], bill_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})

@app.route("/api/bills/<int:bill_id>", methods=["DELETE"])
def delete_bill(bill_id):
    conn = connect_db()
    conn.execute("DELETE FROM bills WHERE bill_id=?", (bill_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})

# ── Chart Data ────────────────────────────────────────────────────────────────

@app.route("/api/charts/expense", methods=["GET"])
def chart_expense():
    user_id = request.args.get("user_id")
    conn = connect_db()
    rows = conn.execute(
        "SELECT category, SUM(amount) as total FROM transactions WHERE user_id=? AND type='expense' GROUP BY category",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"category": r["category"], "total": r["total"]} for r in rows])

@app.route("/api/charts/monthly", methods=["GET"])
def chart_monthly():
    user_id = request.args.get("user_id")
    conn = connect_db()
    rows = conn.execute("""
        SELECT strftime('%m', date) as month, type, SUM(amount) as total
        FROM transactions WHERE user_id=? AND date IS NOT NULL
        GROUP BY month, type ORDER BY month
    """, (user_id,)).fetchall()
    conn.close()
    months_map = {"01":"Jan","02":"Feb","03":"Mar","04":"Apr","05":"May","06":"Jun",
                  "07":"Jul","08":"Aug","09":"Sep","10":"Oct","11":"Nov","12":"Dec"}
    data = {}
    for r in rows:
        m = months_map.get(r["month"], r["month"])
        if m not in data:
            data[m] = {"month": m, "income": 0, "expense": 0}
        data[m][r["type"]] = r["total"]
    return jsonify(list(data.values()))

@app.route("/api/charts/bills", methods=["GET"])
def chart_bills():
    user_id = request.args.get("user_id")
    conn = connect_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM bills WHERE user_id=? GROUP BY status",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"status": r["status"], "count": r["count"]} for r in rows])

if __name__ == "__main__":
    init_db()
    print("\n✅ Finance Manager API running at http://localhost:5000\n")
    app.run(debug=True, port=5000)

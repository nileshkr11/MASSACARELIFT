from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file, session
import io, csv

app = Flask(__name__)
app.secret_key = "change-me"
# --- DB init ---
def init_db():
    conn = sqlite3.connect("data/lifts.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS lifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            lift_type TEXT,
            weight REAL,
            reps INTEGER,
            sets INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Home ---
@app.route("/")
def index():
    conn = sqlite3.connect("data/lifts.db")
    c = conn.cursor()
    squat = c.execute("SELECT * FROM lifts WHERE lift_type='Squat' ORDER BY date DESC").fetchall()
    bench = c.execute("SELECT * FROM lifts WHERE lift_type='Bench' ORDER BY date DESC").fetchall()
    deadlift = c.execute("SELECT * FROM lifts WHERE lift_type='Deadlift' ORDER BY date DESC").fetchall()
    conn.close()
    return render_template("index.html", squat=squat, bench=bench, deadlift=deadlift)

# --- Add Lift ---
@app.route("/add", methods=["POST"])
def add_lift():
    date = request.form["date"]
    lift_type = request.form["lift_type"]
    weight = float(request.form["weight"])
    reps = int(request.form["reps"])
    sets = int(request.form["sets"])
    conn = sqlite3.connect("data/lifts.db")
    c = conn.cursor()
    c.execute("INSERT INTO lifts (date, lift_type, weight, reps, sets) VALUES (?, ?, ?, ?, ?)",
              (date, lift_type, weight, reps, sets))
    conn.commit()
    conn.close()
    return redirect("/")

# --- Delete Lift ---
@app.route("/delete/<int:id>")
def delete_lift(id):
    conn = sqlite3.connect("data/lifts.db")
    c = conn.cursor()
    c.execute("DELETE FROM lifts WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/")

# --- Report Page with Time Filters ---
@app.route("/report/<lift_type>")
def report(lift_type):
    # Get time filter (default = all)
    period = request.args.get("period", "all")

    # Calculate date cutoff
    today = datetime.today()
    if period == "week":
        cutoff = today - timedelta(days=7)
    elif period == "month":
        cutoff = today - timedelta(days=30)
    elif period == "year":
        cutoff = today - timedelta(days=365)
    elif period == "3year":
        cutoff = today - timedelta(days=3*365)
    elif period == "5year":
        cutoff = today - timedelta(days=5*365)
    else:
        cutoff = None  # all time

    # Query data
    conn = sqlite3.connect("data/lifts.db")
    c = conn.cursor()

    if cutoff:
        data = c.execute(
            "SELECT date, weight, reps, sets FROM lifts WHERE lift_type=? AND date>=? ORDER BY date",
            (lift_type, cutoff.strftime("%Y-%m-%d"))
        ).fetchall()
    else:
        data = c.execute(
            "SELECT date, weight, reps, sets FROM lifts WHERE lift_type=? ORDER BY date",
            (lift_type,)
        ).fetchall()

    conn.close()

    dates = [row[0] for row in data]
    weights = [row[1] for row in data]
    reps = [row[2] for row in data]
    sets = [row[3] for row in data]

    return render_template(
        "report.html",
        lift_type=lift_type,
        dates=dates,
        weights=weights,
        reps=reps,
        sets=sets,
        period=period
    )

@app.route("/program")
def program():
    return render_template("program.html")

@app.route("/generate_program", methods=["POST"])
def generate_program():
    squat = float(request.form["squat"])
    bench = float(request.form["bench"])
    deadlift = float(request.form["deadlift"])

    # weeks 1–4 use fixed %; week 5 = test new 1RM (no drop sets)
    scheme = [
        {"week": 1, "main": (0.85, "8–10"), "drop": (0.80, "10 x 2 sets")},
        {"week": 2, "main": (0.90, "7"),    "drop": (0.85, "8 x 2 sets")},
        {"week": 3, "main": (0.95, "5"),    "drop": (0.90, "7 x 2 sets")},
        {"week": 4, "main": (1.00, "3"),    "drop": (0.95, "5 x 2 sets")},
        {"week": 5, "main": None,           "drop": None},  # test day
    ]

    def round_weight(w):  # nearest 2.5 kg
        return round(w / 2.5) * 2.5

    program = []
    for s in scheme:
        if s["main"] is None:
            program.append({
                "week": "Week 5",
                "squat_main": "Test New 1RM",
                "squat_drop": "-",
                "bench_main": "Test New 1RM",
                "bench_drop": "-",
                "dead_main": "Test New 1RM",
                "dead_drop": "-",
            })
            continue

        pct_main, reps_main = s["main"]
        pct_drop, reps_drop = s["drop"]

        program.append({
            "week": f"Week {s['week']}",
            "squat_main": f"{round_weight(squat * pct_main)} x {reps_main}",
            "squat_drop": f"{round_weight(squat * pct_drop)} x {reps_drop}",
            "bench_main": f"{round_weight(bench * pct_main)} x {reps_main}",
            "bench_drop": f"{round_weight(bench * pct_drop)} x {reps_drop}",
            "dead_main":  f"{round_weight(deadlift * pct_main)} x {reps_main}",
            "dead_drop":  f"{round_weight(deadlift * pct_drop)} x {reps_drop}",
        })

    # Save to session for downloading
    session["program"] = program

    return render_template("program_result.html", program=program)


@app.route("/download_program")
def download_program():
    program = session.get("program")
    if not program:
        return redirect(url_for("program"))  # nothing generated yet

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Week",
                     "Squat Main", "Squat Drop (2 sets)",
                     "Bench Main", "Bench Drop (2 sets)",
                     "Deadlift Main", "Deadlift Drop (2 sets)"])
    for row in program:
        writer.writerow([
            row["week"],
            row["squat_main"], row["squat_drop"],
            row["bench_main"], row["bench_drop"],
            row["dead_main"],  row["dead_drop"],
        ])

    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv",
                     as_attachment=True, download_name="program.csv")


if __name__ == "__main__":
    app.run(debug=True)

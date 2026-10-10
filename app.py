from flask import Flask, request, redirect, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import csv
import io


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///interviews.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


db = SQLAlchemy(app)


class Interview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    stage = db.Column(db.String(50), default="Interview")
    stage_started_date = db.Column(db.String(50), nullable=True)
    interview_date = db.Column(db.String(50), nullable=False)
    length = db.Column(db.String(20), nullable=False)
    recruiter = db.Column(db.String(100), default="Rob")
    status = db.Column(db.String(50), default="Waiting for response")
    reminder_count = db.Column(db.Integer, default=0)
    last_reminder_sent = db.Column(db.String(50), nullable=True)
    next_reminder = db.Column(db.String(50), nullable=True)
    last_contact_date = db.Column(db.String(50), nullable=True)
    contact_method = db.Column(db.String(50), nullable=True)
    next_action = db.Column(db.String(200), nullable=True)


class StageHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    interview_id = db.Column(db.Integer, db.ForeignKey("interview.id"), nullable=True)
    candidate = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    stage = db.Column(db.String(50), nullable=False)
    stage_started_date = db.Column(db.String(50), nullable=False)
    stage_ended_date = db.Column(db.String(50), nullable=False)
    followups_in_stage = db.Column(db.Integer, default=0)
    recruiter = db.Column(db.String(100), default="Rob")
    outcome = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.String(500), nullable=True)


with app.app_context():
    db.create_all()


def now_text():
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def parse_date(text):
    if not text:
        return None
    for fmt in ["%Y-%m-%dT%H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def format_date(text):
    if not text:
        return "Not scheduled"
    d = parse_date(text)
    return d.strftime("%m/%d/%Y @ %I:%M %p") if d else text


def input_date(text):
    d = parse_date(text)
    return d.strftime("%Y-%m-%dT%H:%M") if d else ""


def days_between(start, end=None):
    s = parse_date(start)
    e = parse_date(end) if end else datetime.now()
    return max((e - s).days, 0) if s and e else "-"


def days_waiting(i):
    start = parse_date(i.last_contact_date) or parse_date(i.last_reminder_sent) or parse_date(i.stage_started_date) or parse_date(i.interview_date)
    return max((datetime.now() - start).days, 0) if start else "-"


def is_overdue(i):
    return i.status not in ["Completed", "Feedback received"] and parse_date(i.next_reminder) and datetime.now() > parse_date(i.next_reminder)


def base_styles():
    return """
    body{font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:0}.header{background:#1f4e79;color:white;padding:20px 40px}.container{padding:30px 40px}.card{background:white;padding:25px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow-x:auto;margin-bottom:20px}h1{margin:0}.btn{display:inline-block;background:#1f4e79;color:white;padding:10px 16px;border-radius:5px;text-decoration:none;margin-right:8px;margin-bottom:20px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:20px}.summary-card{background:white;padding:18px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);text-align:center}.summary-card strong{display:block;font-size:28px;color:#1f4e79;margin-bottom:5px}table{width:100%;border-collapse:collapse;background:white;min-width:1650px}th{background:#e9eef3;text-align:left;padding:12px}td{padding:12px;border-top:1px solid #ddd;vertical-align:top}.status-waiting{background:#fff3cd;color:#856404;padding:5px 10px;border-radius:20px;font-size:14px;white-space:nowrap}.status-complete{background:#d4edda;color:#155724;padding:5px 10px;border-radius:20px;font-size:14px;white-space:nowrap}.status-final{background:#f8d7da;color:#721c24;padding:5px 10px;border-radius:20px;font-size:14px;white-space:nowrap}.overdue{background:#fff0f0}.small-btn{display:inline-block;padding:6px 10px;border-radius:4px;text-decoration:none;font-size:13px;margin-right:5px;margin-bottom:5px;white-space:nowrap}.complete{background:#28a745;color:white}.delete{background:#dc3545;color:white}.reminder{background:#007bff;color:white}.edit{background:#6c757d;color:white}.move{background:#6f42c1;color:white}.empty{color:#666;padding:20px 0}label{font-weight:bold;display:block;margin-top:15px}input,select,textarea{width:100%;padding:10px;margin-top:5px;border:1px solid #ccc;border-radius:5px;box-sizing:border-box}button{background:#1f4e79;color:white;padding:10px 16px;border:none;border-radius:5px;margin-top:20px;cursor:pointer}.box{background:#f8f9fa;border:1px solid #ddd;border-radius:6px;padding:15px;white-space:pre-wrap;margin-top:8px}.bar-row{margin-bottom:14px}.bar-label{font-weight:bold;margin-bottom:5px}.bar{background:#e9eef3;border-radius:5px;overflow:hidden}.bar-fill{background:#1f4e79;color:white;padding:6px 10px;min-width:24px}
    """


def next_msg_num(i):
    return min(i.reminder_count + 1, 4)


def subject_for(i, n):
    prefix = {"HM Review":"Candidate Review", "On-site Interview":"On-site Feedback", "Offer / No Offer":"Decision"}.get(i.stage, "Feedback")
    if n == 1:
        return f"{prefix} Requested: {i.candidate} - {i.position}"
    if n == 2:
        return f"Follow-Up: {prefix} Needed for {i.candidate}"
    if n == 3:
        return f"Second Follow-Up: {prefix} Needed for {i.candidate}"
    return f"Final Follow-Up: {prefix} Needed for {i.candidate}"


def feedback_request(i):
    if i.stage == "HM Review":
        return """Please reply with whether you would like to move forward with an interview.\n\nHelpful details to include:\nâ¢ Move forward with interview? (Yes / No)\nâ¢ Recommended interview focus areas\nâ¢ Any concerns or questions before scheduling"""
    if i.stage == "Offer / No Offer":
        return """Please reply with the final decision.\n\nHelpful details to include:\nâ¢ Move to offer? (Yes / No)\nâ¢ Any final concerns\nâ¢ If no offer, primary reason for closing out"""
    return """Please reply with feedback on the following areas:\n\nâ¢ Candidate strengths\nâ¢ Opportunities for improvement\nâ¢ Move to next steps? (Yes / No)"""


def generate_message(i):
    n = next_msg_num(i)
    intro = "Thank you for taking the time to review/interview" if n == 1 else "I wanted to follow up regarding"
    msg = f"""Hi {i.person},\n\n{intro} {i.candidate} for the {i.position} role.\n\nCandidate: {i.candidate}\nPosition: {i.position}\nStage: {i.stage}\nDate: {format_date(i.interview_date)}\n\nTo help us move the process forward, {feedback_request(i)}\n\nThank you,\n{i.recruiter}\n"""
    return subject_for(i, n), msg, n


@app.route("/")
def dashboard():
    items = Interview.query.order_by(Interview.interview_date.desc()).all()
    history = StageHistory.query.all()
    avg_days = round(sum(days_between(h.stage_started_date, h.stage_ended_date) for h in history) / len(history), 1) if history else "-"
    rows = ""
    for i in items:
        status_class = "status-complete" if i.status in ["Feedback received", "Completed"] else "status-final" if i.status == "Final reminder sent" else "status-waiting"
        row_class = "overdue" if is_overdue(i) else ""
        message_button = f'<a class="small-btn reminder" href="/message/{i.id}">View Message</a>' if i.status not in ["Feedback received", "Completed"] and i.reminder_count < 4 else ""
        length_display = i.length if i.length == "N/A" else f"{i.length} minutes"
        rows += f"""
        <tr class="{row_class}">
            <td>{i.candidate}</td><td>{i.position}</td><td>{i.stage}</td><td>{format_date(i.stage_started_date)}</td><td>{days_between(i.stage_started_date)}</td><td>{i.person}</td><td>{format_date(i.interview_date)}</td><td>{length_display}</td><td><span class="{status_class}">{i.status}</span></td><td>{i.reminder_count}</td><td>{format_date(i.last_reminder_sent)}</td><td>{format_date(i.next_reminder)}</td><td>{format_date(i.last_contact_date)}</td><td>{i.contact_method or '-'}</td><td>{days_waiting(i)}</td><td>{i.next_action or '-'}</td>
            <td>{message_button}<a class="small-btn reminder" href="/contacted/{i.id}/Email">Email</a><a class="small-btn reminder" href="/contacted/{i.id}/Teams">Teams</a><a class="small-btn move" href="/move-stage/{i.id}">Move Stage</a><a class="small-btn edit" href="/edit/{i.id}">Edit</a><a class="small-btn complete" href="/complete/{i.id}">Complete</a><a class="small-btn delete" href="/delete/{i.id}">Delete</a></td>
        </tr>"""
    return f"""
    <html><head><title>Recruiting Follow-Up Tracker</title><style>{base_styles()}</style></head><body>
    <div class="header"><h1>Recruiting Follow-Up Tracker</h1><p>Track follow-ups, stage aging, and hiring manager bottlenecks.</p></div>
    <div class="container">
        <div class="summary">
            <div class="summary-card"><strong>{len(items)}</strong>Active Follow-Ups</div><div class="summary-card"><strong>{len([x for x in items if x.status == 'Waiting for response'])}</strong>Waiting</div><div class="summary-card"><strong>{len([x for x in items if x.status == 'Completed'])}</strong>Completed</div><div class="summary-card"><strong>{len([x for x in items if is_overdue(x)])}</strong>Overdue</div><div class="summary-card"><strong>{len(history)}</strong>Closed Stage Records</div><div class="summary-card"><strong>{avg_days}</strong>Avg Days in Closed Stages</div><div class="summary-card"><strong>{len(set([x.person for x in items]))}</strong>People Tracked</div><div class="summary-card"><strong>{len([x for x in items if x.status == 'Final reminder sent'])}</strong>Final Reminder</div>
        </div>
        <div class="card"><a class="btn" href="/add">+ Add Follow-Up</a><a class="btn" href="/add-history">+ Add Historical Stage</a><a class="btn" href="/export">Export Active CSV</a><a class="btn" href="/export-history">Export Stage History CSV</a><a class="btn" href="/analytics">Analytics</a>
        <table><tr><th>Candidate</th><th>Position</th><th>Current Stage</th><th>Stage Started</th><th>Days in Stage</th><th>Person</th><th>Date/Time</th><th>Length</th><th>Status</th><th>Reminder #</th><th>Last Reminder Sent</th><th>Next Follow-Up Due</th><th>Last Contact</th><th>Method</th><th>Days Waiting</th><th>Next Action</th><th>Actions</th></tr>{rows}</table>
        {"<p class='empty'>No follow-ups added yet.</p>" if not items else ""}</div>
    </div></body></html>"""


@app.route("/add", methods=["GET", "POST"])
def add_interview():
    if request.method == "POST":
        stage_started = request.form.get("stage_started_date") or request.form["date"]
        item = Interview(candidate=request.form["candidate"], person=request.form["person"], position=request.form["position"], stage=request.form["stage"], stage_started_date=stage_started, interview_date=request.form["date"], length=request.form["length"], recruiter=request.form["recruiter"], next_action=request.form.get("next_action"))
        db.session.add(item); db.session.commit(); return redirect("/")
    return f"""<html><head><title>Add Follow-Up</title><style>{base_styles()}</style></head><body><div class="header"><h1>Add Follow-Up</h1></div><div class="container"><div class="card" style="max-width:650px;"><form method="post">
    <label>Candidate First Name or Initials</label><input name="candidate" required><label>Person to Follow Up With</label><input name="person" required><label>Position</label><input name="position" required><label>Stage</label><select name="stage"><option>HM Review</option><option>Interview</option><option>On-site Interview</option><option>Offer / No Offer</option></select><label>Stage Started Date</label><input name="stage_started_date" type="datetime-local"><label>Date/Time</label><input name="date" type="datetime-local" required><label>Length / Duration</label><select name="length"><option>N/A</option><option>30</option><option>45</option><option>60</option><option>90</option></select><label>Recruiter Name</label><input name="recruiter" value="Rob" required><label>Next Action</label><input name="next_action"><button type="submit">Create Follow-Up</button></form><p><a href="/">Back to Dashboard</a></p></div></div></body></html>"""


@app.route("/move-stage/<int:interview_id>", methods=["GET", "POST"])
def move_stage(interview_id):
    i = Interview.query.get_or_404(interview_id)
    if request.method == "POST":
        ended = request.form.get("stage_ended_date") or now_text()
        hist = StageHistory(interview_id=i.id, candidate=i.candidate, person=i.person, position=i.position, stage=i.stage, stage_started_date=request.form.get("stage_started_date") or i.stage_started_date or i.interview_date, stage_ended_date=ended, followups_in_stage=int(request.form.get("followups_in_stage") or i.reminder_count or 0), recruiter=i.recruiter, outcome=request.form.get("outcome"), notes=request.form.get("notes"))
        i.stage = request.form["new_stage"]; i.stage_started_date = request.form.get("new_stage_started_date") or ended; i.reminder_count = 0; i.last_reminder_sent = None; i.next_reminder = None; i.last_contact_date = None; i.contact_method = None; i.status = "Waiting for response"; i.next_action = request.form.get("next_action") or None
        db.session.add(hist); db.session.commit(); return redirect("/")
    return f"""<html><head><title>Move Stage</title><style>{base_styles()}</style></head><body><div class="header"><h1>Move Stage</h1><p>Close the current stage and start the next one.</p></div><div class="container"><div class="card" style="max-width:700px;"><p><strong>Candidate:</strong> {i.candidate}</p><p><strong>Current Stage:</strong> {i.stage}</p><form method="post"><label>Current Stage Started Date</label><input name="stage_started_date" type="datetime-local" value="{input_date(i.stage_started_date or i.interview_date)}"><label>Current Stage Ended Date</label><input name="stage_ended_date" type="datetime-local" value="{now_text()}"><label>Follow-Ups Needed in This Stage</label><input name="followups_in_stage" type="number" min="0" value="{i.reminder_count}"><label>Outcome</label><input name="outcome" placeholder="Moved to Interview, Rejected, Offer discussion"><label>Notes</label><textarea name="notes" rows="3"></textarea><label>New Stage</label><select name="new_stage"><option>HM Review</option><option>Interview</option><option>On-site Interview</option><option>Offer / No Offer</option></select><label>New Stage Started Date</label><input name="new_stage_started_date" type="datetime-local" value="{now_text()}"><label>Next Action</label><input name="next_action"><button type="submit">Move Stage</button></form><p><a href="/">Back to Dashboard</a></p></div></div></body></html>"""


@app.route("/add-history", methods=["GET", "POST"])
def add_history():
    if request.method == "POST":
        h = StageHistory(candidate=request.form["candidate"], person=request.form["person"], position=request.form["position"], stage=request.form["stage"], stage_started_date=request.form["stage_started_date"], stage_ended_date=request.form["stage_ended_date"], followups_in_stage=int(request.form.get("followups_in_stage") or 0), recruiter=request.form.get("recruiter") or "Rob", outcome=request.form.get("outcome"), notes=request.form.get("notes"))
        db.session.add(h); db.session.commit(); return redirect("/analytics")
    return f"""<html><head><title>Add Historical Stage</title><style>{base_styles()}</style></head><body><div class="header"><h1>Add Historical Stage</h1><p>Use this when you forgot to add someone earlier but still want the analytics.</p></div><div class="container"><div class="card" style="max-width:700px;"><form method="post"><label>Candidate</label><input name="candidate" required><label>Person Responsible</label><input name="person" required><label>Position</label><input name="position" required><label>Stage</label><select name="stage"><option>HM Review</option><option>Interview</option><option>On-site Interview</option><option>Offer / No Offer</option></select><label>Stage Started Date</label><input name="stage_started_date" type="datetime-local" required><label>Stage Ended Date</label><input name="stage_ended_date" type="datetime-local" required><label>Follow-Ups Needed in This Stage</label><input name="followups_in_stage" type="number" min="0" value="0"><label>Recruiter Name</label><input name="recruiter" value="Rob"><label>Outcome</label><input name="outcome"><label>Notes</label><textarea name="notes" rows="3"></textarea><button type="submit">Save Historical Stage</button></form><p><a href="/">Back to Dashboard</a></p></div></div></body></html>"""


@app.route("/edit/<int:interview_id>", methods=["GET", "POST"])
def edit_interview(interview_id):
    i = Interview.query.get_or_404(interview_id)
    if request.method == "POST":
        i.candidate=request.form["candidate"]; i.person=request.form["person"]; i.position=request.form["position"]; i.stage=request.form["stage"]; i.stage_started_date=request.form.get("stage_started_date") or None; i.interview_date=request.form["date"]; i.length=request.form["length"]; i.recruiter=request.form["recruiter"]; i.status=request.form["status"]; i.last_contact_date=request.form.get("last_contact_date") or None; i.contact_method=request.form.get("contact_method") or None; i.next_action=request.form.get("next_action") or None
        db.session.commit(); return redirect("/")
    return f"""<html><head><title>Edit Follow-Up</title><style>{base_styles()}</style></head><body><div class="header"><h1>Edit Follow-Up</h1></div><div class="container"><div class="card" style="max-width:650px;"><form method="post"><label>Candidate</label><input name="candidate" value="{i.candidate}" required><label>Person</label><input name="person" value="{i.person}" required><label>Position</label><input name="position" value="{i.position}" required><label>Stage</label><input name="stage" value="{i.stage}" required><label>Stage Started Date</label><input name="stage_started_date" type="datetime-local" value="{input_date(i.stage_started_date)}"><label>Status</label><select name="status"><option {"selected" if i.status == "Waiting for response" else ""}>Waiting for response</option><option {"selected" if i.status == "Final reminder sent" else ""}>Final reminder sent</option><option {"selected" if i.status == "Feedback received" else ""}>Feedback received</option><option {"selected" if i.status == "Completed" else ""}>Completed</option></select><label>Date/Time</label><input name="date" type="datetime-local" value="{input_date(i.interview_date)}" required><label>Length</label><input name="length" value="{i.length}" required><label>Recruiter</label><input name="recruiter" value="{i.recruiter}" required><label>Last Contact</label><input name="last_contact_date" type="datetime-local" value="{input_date(i.last_contact_date)}"><label>Contact Method</label><input name="contact_method" value="{i.contact_method or ""}"><label>Next Action</label><input name="next_action" value="{i.next_action or ""}"><button type="submit">Save Changes</button></form><p><a href="/">Back to Dashboard</a></p></div></div></body></html>"""


@app.route("/message/<int:interview_id>")
def view_message(interview_id):
    i = Interview.query.get_or_404(interview_id); subj, msg, num = generate_message(i)
    return f"""<html><head><title>Reminder Message</title><style>{base_styles()}</style></head><body><div class="header"><h1>{i.stage} - Reminder {num}</h1></div><div class="container"><div class="card" style="max-width:850px;"><p><strong>Subject:</strong></p><div class="box">{subj}</div><p><strong>Message:</strong></p><div class="box">{msg}</div><a class="btn" href="/mark-reminder-sent/{i.id}">Mark Reminder Sent</a><a class="btn" href="/">Back</a></div></div></body></html>"""


@app.route("/mark-reminder-sent/<int:interview_id>")
def mark_reminder_sent(interview_id):
    i = Interview.query.get_or_404(interview_id)
    if i.status not in ["Feedback received", "Completed"] and i.reminder_count < 4:
        now = datetime.now(); i.reminder_count += 1; i.last_reminder_sent = now.strftime("%Y-%m-%dT%H:%M"); i.last_contact_date = i.last_reminder_sent; i.contact_method = "Email"
        if i.reminder_count == 4: i.status = "Final reminder sent"; i.next_reminder = None
        else: i.next_reminder = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")
        db.session.commit()
    return redirect("/")


@app.route("/contacted/<int:interview_id>/<method>")
def contacted(interview_id, method):
    i = Interview.query.get_or_404(interview_id); i.last_contact_date = now_text(); i.contact_method = method; db.session.commit(); return redirect("/")


@app.route("/complete/<int:interview_id>")
def complete(interview_id):
    i = Interview.query.get_or_404(interview_id); i.status = "Completed"; i.next_reminder = None; db.session.commit(); return redirect("/")


@app.route("/delete/<int:interview_id>")
def delete(interview_id):
    i = Interview.query.get_or_404(interview_id); db.session.delete(i); db.session.commit(); return redirect("/")


@app.route("/export")
def export_active():
    out=io.StringIO(); w=csv.writer(out); w.writerow(["Candidate","Person","Position","Current Stage","Stage Started","Days in Current Stage","Status","Reminder Count","Last Contact","Contact Method","Days Waiting","Next Action"])
    for i in Interview.query.all(): w.writerow([i.candidate,i.person,i.position,i.stage,i.stage_started_date,days_between(i.stage_started_date),i.status,i.reminder_count,i.last_contact_date,i.contact_method,days_waiting(i),i.next_action])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=active_recruiting_followups.csv"})


@app.route("/export-history")
def export_history():
    out=io.StringIO(); w=csv.writer(out); w.writerow(["Candidate","Person","Position","Stage","Started","Ended","Days in Stage","Follow-Ups","Recruiter","Outcome","Notes"])
    for h in StageHistory.query.all(): w.writerow([h.candidate,h.person,h.position,h.stage,h.stage_started_date,h.stage_ended_date,days_between(h.stage_started_date,h.stage_ended_date),h.followups_in_stage,h.recruiter,h.outcome,h.notes])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=stage_history_analytics.csv"})


def bar_chart(title, counter):
    if not counter: return f"<h2>{title}</h2><p>No data yet.</p>"
    maxv=max(counter.values()); rows=""
    for label,val in counter.most_common(): rows += f'<div class="bar-row"><div class="bar-label">{label}: {val}</div><div class="bar"><div class="bar-fill" style="width:{int((val/maxv)*100)}%;">{val}</div></div></div>'
    return f"<h2>{title}</h2>{rows}"


def avg_table(title, data):
    if not data: return f"<h2>{title}</h2><p>No historical data yet.</p>"
    rows=""
    for label, vals in sorted(data.items()): rows += f"<tr><td>{label}</td><td>{len(vals)}</td><td>{round(sum(v['days'] for v in vals)/len(vals),1)}</td><td>{round(sum(v['followups'] for v in vals)/len(vals),1)}</td></tr>"
    return f"<h2>{title}</h2><table style='min-width:700px;'><tr><th>Name</th><th>Closed Stage Records</th><th>Avg Days in Stage</th><th>Avg Follow-Ups Needed</th></tr>{rows}</table>"


@app.route("/analytics")
def analytics():
    items=Interview.query.all(); hist=StageHistory.query.all(); by_person=defaultdict(list); by_stage=defaultdict(list)
    for h in hist:
        d=days_between(h.stage_started_date,h.stage_ended_date)
        if d != "-":
            rec={"days":d,"followups":h.followups_in_stage or 0}; by_person[h.person].append(rec); by_stage[h.stage].append(rec)
    return f"""<html><head><title>Analytics</title><style>{base_styles()}</style></head><body><div class="header"><h1>Recruiting Follow-Up Analytics</h1><p>Identify stage bottlenecks and follow-up patterns.</p></div><div class="container"><a class="btn" href="/">Back</a><a class="btn" href="/export-history">Export Stage History CSV</a><a class="btn" href="/add-history">Add Historical Stage</a><div class="card">{avg_table("Average Days and Follow-Ups by Person", by_person)}</div><div class="card">{avg_table("Average Days and Follow-Ups by Stage", by_stage)}</div><div class="card">{bar_chart("Current Active Follow-Ups by Stage", Counter([i.stage for i in items]))}</div><div class="card">{bar_chart("Current Active Follow-Ups by Person", Counter([i.person for i in items]))}</div><div class="card">{bar_chart("Current Active Follow-Ups by Status", Counter([i.status for i in items]))}</div></div></body></html>"""


if __name__ == "__main__":
    app.run(debug=True, port=5001)


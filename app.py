import os
import re
import csv
import io
import sqlite3
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, g, session, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-this-in-prod-v3'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DATABASE'] = 'instance/thesis.db'
app.config['ADMIN_USERNAME'] = 'admin'
app.config['ADMIN_PASSWORD'] = 'admin123'

DEPARTMENTS = [
    "Pharmaceutical and Medicinal Chemistry",
    "Pharmaceutical Microbiology and Biotechnology",
    "Pharmaceutics",
    "Pharmaceutical Technology and Industrial Pharmacy",
    "Pharmacognosy and Environmental Medicine",
    "Pharmacology and Toxicology",
    "Clinical Pharmacy and Pharmacy Management",
]

DEPT_CODES = {
    "Pharmaceutical and Medicinal Chemistry":           "PMC",
    "Pharmaceutical Microbiology and Biotechnology":    "PMB",
    "Pharmaceutics":                                    "PHA",
    "Pharmaceutical Technology and Industrial Pharmacy":"PTI",
    "Pharmacognosy and Environmental Medicine":         "PGN",
    "Pharmacology and Toxicology":                      "PLT",
    "Clinical Pharmacy and Pharmacy Management":        "CPM",
}

DATA_SOURCES = [
    "In vitro", "In vivo", "In silico", "Ex vivo",
    "Clinical", "Epidemiological", "Mixed",
]

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('instance', exist_ok=True)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        ensure_schema(db)
        ensure_default_admin(db)
        db.commit()
        print("Database initialized.")


@app.before_request
def ensure_app_db_ready():
    with app.app_context():
        db = get_db()
        ensure_schema(db)
        ensure_default_admin(db)
        db.commit()


def ensure_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            full_name TEXT,
            email TEXT,
            can_edit_thesis INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS supervisors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            department TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS students (
            reg_number TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            entry_year INTEGER NOT NULL,
            gender TEXT NOT NULL,
            cgpa REAL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT,
            student_reg_number TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            supervisors_text TEXT NOT NULL,
            department TEXT NOT NULL,
            keywords TEXT NOT NULL,
            work_type TEXT NOT NULL,
            abstract TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            csv_file_path TEXT DEFAULT '',
            plants_used TEXT DEFAULT '',
            aim TEXT DEFAULT '',
            methods_summary TEXT DEFAULT '',
            results_summary TEXT DEFAULT '',
            conclusion TEXT DEFAULT '',
            compounds_studied TEXT DEFAULT '',
            biological_targets TEXT DEFAULT '',
            research_area TEXT DEFAULT '',
            data_source TEXT DEFAULT '',
            tools_software TEXT DEFAULT '',
            experimental_techniques TEXT DEFAULT '',
            submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_reg_number) REFERENCES students (reg_number)
        )
    """)
    db.execute("CREATE TABLE IF NOT EXISTS otp_store (id INTEGER PRIMARY KEY AUTOINCREMENT, purpose TEXT, identifier TEXT, otp_hash TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")


def ensure_default_admin(db):
    admin_user = db.execute(
        "SELECT id FROM users WHERE username = ? AND role = 'admin'",
        (app.config['ADMIN_USERNAME'],),
    ).fetchone()
    if not admin_user:
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, 'admin', 'System Administrator', 'admin@kemistri.local', 1)",
            (app.config['ADMIN_USERNAME'], generate_password_hash(app.config['ADMIN_PASSWORD'])),
        )


def generate_project_id(department, db):
    """Return a unique departmental project ID, e.g. PMC0001."""
    prefix = DEPT_CODES.get(department, "GEN")
    pattern = f"{prefix}%"
    row = db.execute(
        "SELECT project_id FROM theses WHERE department = ? AND project_id LIKE ? ORDER BY project_id DESC LIMIT 1",
        (department, pattern),
    ).fetchone()

    if row and row['project_id']:
        match = re.search(rf"^{re.escape(prefix)}(\d+)$", str(row['project_id']).upper())
        if match:
            next_number = int(match.group(1)) + 1
            return f"{prefix}{next_number:04d}"

    count = db.execute(
        "SELECT COUNT(*) FROM theses WHERE department = ?",
        (department,),
    ).fetchone()[0]
    return f"{prefix}{count + 1:04d}"


def normalize_name(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def split_supervisors(value):
    if not value:
        return []
    return [normalize_name(part) for part in str(value).split(',') if normalize_name(part)]


def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return get_db().execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()


def login_required(role=None):
    def decorator(view_func):
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if not user:
                flash('Please log in to continue.', 'error')
                return redirect(url_for('login'))
            if role and user['role'] != role:
                flash('You do not have access to that page.', 'error')
                return redirect(url_for('index'))
            return view_func(*args, **kwargs)
        wrapped.__name__ = view_func.__name__
        return wrapped
    return decorator


def can_edit_thesis(student_reg_number, user):
    if not user:
        return False
    if user['role'] == 'admin':
        return True
    if user['role'] == 'student':
        return user['username'] == student_reg_number and bool(user['can_edit_thesis'])
    return False


# ---------------------------------------------------------------------------
# Shared filter logic (browse + download-csv share identical WHERE logic)
# ---------------------------------------------------------------------------

def _apply_filters(conditions, params, year, supervisor, department, plant, keyword, q):
    if year:
        conditions.append("s.entry_year = ?")
        params.append(year)
    if supervisor:
        conditions.append("t.supervisors_text LIKE ?")
        params.append(f"%{supervisor}%")
    if department:
        conditions.append("t.department = ?")
        params.append(department)
    if plant:
        conditions.append("(t.plants_used LIKE ? OR t.compounds_studied LIKE ?)")
        params += [f"%{plant}%", f"%{plant}%"]
    if keyword:
        conditions.append("t.keywords LIKE ?")
        params.append(f"%{keyword}%")
    if q:
        conditions.append(
            "(t.title LIKE ? OR t.keywords LIKE ? OR t.compounds_studied LIKE ?"
            " OR s.name LIKE ? OR t.abstract LIKE ?)"
        )
        params += [f"%{q}%"] * 5


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


# ── Public browse ──────────────────────────────────────────────────────────

@app.route('/browse')
def browse():
    db = get_db()

    year       = request.args.get('year',       '')
    supervisor = request.args.get('supervisor', '')
    department = request.args.get('department', '')
    plant      = request.args.get('plant',      '')
    keyword    = request.args.get('keyword',    '')
    q          = request.args.get('q',          '')

    conditions, params = [], []
    _apply_filters(conditions, params, year, supervisor, department, plant, keyword, q)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT t.id, t.project_id, t.title,
               s.name AS student_name, s.reg_number AS student_reg_number,
               t.department, t.supervisors_text, s.entry_year,
               t.plants_used, t.keywords, t.compounds_studied,
               t.work_type, t.research_area, t.biological_targets,
               t.data_source, t.submission_date
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
        {where}
        ORDER BY t.submission_date DESC
    """
    results = [dict(r) for r in db.execute(sql, params).fetchall()]

    all_supervisors = [dict(r) for r in
                       db.execute('SELECT DISTINCT name FROM supervisors ORDER BY name').fetchall()]
    all_years = [dict(r) for r in
                 db.execute('SELECT DISTINCT entry_year FROM students ORDER BY entry_year DESC').fetchall()]

    return render_template(
        'browse.html',
        results=results,
        departments=DEPARTMENTS,
        supervisors=all_supervisors,
        years=all_years,
        filters=dict(year=year, supervisor=supervisor, department=department,
                     plant=plant, keyword=keyword, q=q),
    )


# ── CSV download ───────────────────────────────────────────────────────────

@app.route('/download-csv')
def download_csv():
    db = get_db()

    ids        = request.args.getlist('ids')
    year       = request.args.get('year',       '')
    supervisor = request.args.get('supervisor', '')
    department = request.args.get('department', '')
    plant      = request.args.get('plant',      '')
    keyword    = request.args.get('keyword',    '')
    q          = request.args.get('q',          '')

    conditions, params = [], []
    if ids:
        placeholders = ','.join('?' * len(ids))
        conditions.append(f"t.id IN ({placeholders})")
        params.extend(ids)
    else:
        _apply_filters(conditions, params, year, supervisor, department, plant, keyword, q)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT t.project_id, t.title, s.name AS student_name, s.reg_number,
               t.department, t.supervisors_text, s.entry_year,
               t.plants_used, t.aim, t.methods_summary, t.results_summary,
               t.conclusion, t.keywords, t.compounds_studied,
               t.biological_targets, t.research_area, t.data_source,
               t.tools_software, t.experimental_techniques,
               t.work_type, t.abstract, t.submission_date
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
        {where}
        ORDER BY t.submission_date DESC
    """
    rows = db.execute(sql, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Project ID', 'Title', 'Author', 'Reg Number', 'Department', 'Supervisor',
        'Year', 'Plants/Materials Used', 'Aim', 'Methods Summary', 'Results Summary',
        'Conclusion', 'Keywords', 'Compounds Studied', 'Biological Targets',
        'Research Area', 'Data Source', 'Tools/Software', 'Experimental Techniques',
        'Work Type', 'Abstract', 'Submission Date',
    ])
    for row in rows:
        r = dict(row)
        writer.writerow([
            r.get('project_id', ''),      r.get('title', ''),
            r.get('student_name', ''),    r.get('reg_number', ''),
            r.get('department', ''),      r.get('supervisors_text', ''),
            r.get('entry_year', ''),      r.get('plants_used', ''),
            r.get('aim', ''),             r.get('methods_summary', ''),
            r.get('results_summary', ''), r.get('conclusion', ''),
            r.get('keywords', ''),        r.get('compounds_studied', ''),
            r.get('biological_targets',''),r.get('research_area', ''),
            r.get('data_source', ''),     r.get('tools_software', ''),
            r.get('experimental_techniques', ''),
            r.get('work_type', ''),       r.get('abstract', ''),
            r.get('submission_date', ''),
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=kemistri_theses_export.csv'},
    )


# ── Thesis detail ──────────────────────────────────────────────────────────

@app.route('/thesis/<int:id>')
def thesis_detail(id):
    db = get_db()
    row = db.execute("""
        SELECT t.*, s.name AS student_name, s.email, s.gender, s.cgpa, s.entry_year
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
        WHERE t.id = ?
    """, (id,)).fetchone()
    if not row:
        return "Thesis not found", 404
    return render_template('thesis_detail.html', thesis=dict(row))


# ── Submit ─────────────────────────────────────────────────────────────────

@app.route('/submit', methods=('GET', 'POST'))
@login_required(role='student')
def submit():
    db = get_db()
    user = get_current_user()

    if request.method == 'GET':
        if user and user['role'] == 'student':
            existing_thesis = db.execute('SELECT * FROM theses WHERE student_reg_number = ?', (user['username'],)).fetchone()
            if existing_thesis and not user['can_edit_thesis']:
                flash('Submission blocked: this thesis is already locked. Ask the admin to grant edit permission.', 'error')
                return redirect(url_for('browse'))

    supervisors = [dict(r) for r in db.execute('SELECT name, department FROM supervisors').fetchall()]

    if request.method == 'POST':
        try:
            reg_number = request.form.get('reg_number', '').strip()
            if user['username'] != reg_number and not user['can_edit_thesis']:
                flash('You can only submit or edit your own registration number.', 'error')
                return redirect(url_for('browse'))

            existing_thesis = db.execute('SELECT * FROM theses WHERE student_reg_number = ?', (reg_number,)).fetchone()
            if existing_thesis and not user['can_edit_thesis']:
                flash('Duplicate submission blocked: this registration number is already locked. Contact the admin for explicit permission.', 'error')
                return redirect(url_for('browse'))

            # ── Student info
            name        = request.form['name']
            email       = request.form['email']
            entry_year  = request.form['entry_year']
            gender      = request.form['gender']
            cgpa        = request.form['cgpa']

            # ── Thesis basics
            title            = request.form['title']
            department       = request.form['department']
            supervisor_names = request.form['supervisor_names']
            keywords         = request.form['keywords']
            work_type        = request.form['work_type']
            abstract         = request.form['abstract']

            # ── Research detail fields (form)
            plants_used             = request.form.get('plants_used', '')
            aim                     = request.form.get('aim', '')
            methods_summary         = request.form.get('methods_summary', '')
            results_summary         = request.form.get('results_summary', '')
            conclusion              = request.form.get('conclusion', '')
            compounds_studied       = request.form.get('compounds_studied', '')
            biological_targets      = request.form.get('biological_targets', '')
            research_area           = request.form.get('research_area', '')
            data_source             = request.form.get('data_source', '')
            tools_software          = request.form.get('tools_software', '')
            experimental_techniques = request.form.get('experimental_techniques', '')

            # ── Optional CSV upload — fills any blank research fields
            csv_file = request.files.get('csv_file')
            csv_filename = ''
            if csv_file and csv_file.filename:
                ext = csv_file.filename.rsplit('.', 1)[-1].lower()
                if ext == 'csv':
                    csv_filename = secure_filename(f"{reg_number.replace('/', '_')}_{csv_file.filename}")
                    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
                    csv_file.save(csv_path)
                    try:
                        with open(csv_path, newline='', encoding='utf-8-sig') as f:
                            reader = csv.DictReader(f)
                            for csv_row in reader:
                                r = {k.strip().lower().replace(' ', '_').replace('/', '_'): v.strip() for k, v in csv_row.items()}
                                if not plants_used:
                                    plants_used = r.get('plants_materials_used', r.get('plants_used', ''))
                                if not aim: aim = r.get('aim', '')
                                if not methods_summary: methods_summary = r.get('methods_summary', '')
                                if not results_summary: results_summary = r.get('results_summary', '')
                                if not conclusion: conclusion = r.get('conclusion', '')
                                if not compounds_studied: compounds_studied = r.get('compounds_studied', '')
                                if not biological_targets: biological_targets = r.get('biological_targets', '')
                                if not research_area: research_area = r.get('research_area', '')
                                if not data_source: data_source = r.get('data_source', '')
                                if not tools_software: tools_software = r.get('tools_software', r.get('tools_or_software_used', ''))
                                if not experimental_techniques: experimental_techniques = r.get('experimental_techniques', '')
                                break
                    except Exception as csv_err:
                        flash(f'CSV parsed with warning: {csv_err}. Form values used.', 'warning')

            pdf_file = request.files.get('file')
            filename = ''
            if pdf_file and pdf_file.filename:
                filename = secure_filename(f"{reg_number.replace('/', '_')}_{pdf_file.filename}")
                pdf_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            project_id = generate_project_id(department, db)

            if db.execute('SELECT 1 FROM students WHERE reg_number = ?', (reg_number,)).fetchone():
                db.execute(
                    'UPDATE students SET email = ?, name = ?, entry_year = ?, gender = ?, cgpa = ? WHERE reg_number = ?',
                    (email, name, entry_year, gender, cgpa, reg_number),
                )
            else:
                db.execute(
                    'INSERT INTO students (reg_number, email, name, entry_year, gender, cgpa) VALUES (?, ?, ?, ?, ?, ?)',
                    (reg_number, email, name, entry_year, gender, cgpa),
                )

            if existing_thesis:
                if not user['can_edit_thesis']:
                    flash('This thesis cannot be edited without admin permission.', 'error')
                    return redirect(url_for('browse'))
                db.execute(
                    '''UPDATE theses SET project_id = ?, title = ?, supervisors_text = ?, department = ?, keywords = ?, work_type = ?, abstract = ?, file_path = ?, csv_file_path = ?, plants_used = ?, aim = ?, methods_summary = ?, results_summary = ?, conclusion = ?, compounds_studied = ?, biological_targets = ?, research_area = ?, data_source = ?, tools_software = ?, experimental_techniques = ? WHERE student_reg_number = ?''',
                    (project_id, title, supervisor_names, department, keywords, work_type, abstract, filename, csv_filename, plants_used, aim, methods_summary, results_summary, conclusion, compounds_studied, biological_targets, research_area, data_source, tools_software, experimental_techniques, reg_number),
                )
            else:
                db.execute(
                    '''INSERT INTO theses (project_id, student_reg_number, title, supervisors_text, department, keywords, work_type, abstract, file_path, csv_file_path, plants_used, aim, methods_summary, results_summary, conclusion, compounds_studied, biological_targets, research_area, data_source, tools_software, experimental_techniques) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (project_id, reg_number, title, supervisor_names, department, keywords, work_type, abstract, filename, csv_filename, plants_used, aim, methods_summary, results_summary, conclusion, compounds_studied, biological_targets, research_area, data_source, tools_software, experimental_techniques),
                )

            db.commit()
            flash('Thesis submitted successfully!', 'success')
            return redirect(url_for('browse'))
        except Exception as error:
            flash(f'Error submitting thesis: {error}', 'error')

    return render_template('submit.html', departments=DEPARTMENTS, supervisors=supervisors, data_sources=DATA_SOURCES)


# ── CSV template download ──────────────────────────────────────────────────

@app.route('/download-template')
def download_template():
    from flask import send_from_directory
    return send_from_directory(
        'static',
        'kemistri_submission_template.csv',
        as_attachment=True,
        download_name='kemistri_submission_template.csv',
    )


# ── Search (quick, from header) ────────────────────────────────────────────

@app.route('/search')
def search():
    q = request.args.get('q', '')
    if not q:
        return redirect(url_for('browse'))
    return redirect(url_for('browse', q=q))


# ── Supervisors ────────────────────────────────────────────────────────────

@app.route('/supervisors')
def supervisor_list():
    db = get_db()
    supervisors = [dict(r) for r in db.execute('SELECT * FROM supervisors').fetchall()]
    return render_template('supervisor.html', supervisors=supervisors)


@app.route('/supervisor/<int:id>')
def supervisor_dashboard(id):
    db = get_db()
    me_row = db.execute('SELECT * FROM supervisors WHERE id = ?', (id,)).fetchone()
    if not me_row:
        return "Supervisor not found", 404
    me = dict(me_row)

    all_theses = [dict(r) for r in db.execute("""
        SELECT t.*, s.name AS student_name
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
    """).fetchall()]

    my_students = []
    for thesis in all_theses:
        thesis_supervisors = set(split_supervisors(thesis.get('supervisors_text', '')))
        if normalize_name(me['name']) in thesis_supervisors:
            my_students.append(thesis)
    return render_template('supervisor_dashboard.html', supervisor=me, theses=my_students)


# ── Login / Logout ──────────────────────────────────────────────────────────

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user_type = (request.form.get('user_type') or 'student').strip()

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ? AND role = ?',
            (username, user_type),
        ).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            flash('Login successful.', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('browse'))

        flash('Invalid credentials.', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/admin')
@login_required(role='admin')
def admin_dashboard():
    db = get_db()
    theses = [dict(r) for r in db.execute('''
        SELECT t.*, s.name AS student_name, s.email AS student_email
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
        ORDER BY t.submission_date DESC
    ''').fetchall()]
    students = [dict(r) for r in db.execute('SELECT * FROM students ORDER BY name ASC').fetchall()]
    return render_template('admin_dashboard.html', theses=theses, students=students)


@app.route('/admin/thesis/<int:id>/edit', methods=('GET', 'POST'))
@login_required(role='admin')
def admin_thesis_edit(id):
    db = get_db()
    thesis = db.execute('''
        SELECT t.*, s.name AS student_name, s.email AS student_email
        FROM theses t
        JOIN students s ON t.student_reg_number = s.reg_number
        WHERE t.id = ?
    ''', (id,)).fetchone()
    if not thesis:
        return 'Thesis not found', 404

    if request.method == 'POST':
        db.execute(
            '''
            UPDATE theses SET
                title = ?, supervisors_text = ?, department = ?, keywords = ?,
                work_type = ?, abstract = ?, plants_used = ?, aim = ?, methods_summary = ?,
                results_summary = ?, conclusion = ?, compounds_studied = ?, biological_targets = ?,
                research_area = ?, data_source = ?, tools_software = ?, experimental_techniques = ?
            WHERE id = ?
            ''',
            (
                request.form['title'],
                request.form['supervisors_text'],
                request.form['department'],
                request.form['keywords'],
                request.form['work_type'],
                request.form['abstract'],
                request.form.get('plants_used', ''),
                request.form.get('aim', ''),
                request.form.get('methods_summary', ''),
                request.form.get('results_summary', ''),
                request.form.get('conclusion', ''),
                request.form.get('compounds_studied', ''),
                request.form.get('biological_targets', ''),
                request.form.get('research_area', ''),
                request.form.get('data_source', ''),
                request.form.get('tools_software', ''),
                request.form.get('experimental_techniques', ''),
                id,
            ),
        )
        db.commit()
        flash('Thesis record updated by admin.', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_thesis_edit.html', thesis=dict(thesis))


@app.route('/admin/student/<reg_number>', methods=('GET', 'POST'))
@login_required(role='admin')
def admin_student_permissions(reg_number):
    db = get_db()
    student = db.execute('SELECT * FROM students WHERE reg_number = ?', (reg_number,)).fetchone()
    if not student:
        return 'Student not found', 404

    user = db.execute('SELECT * FROM users WHERE username = ? AND role = ?', (reg_number, 'student')).fetchone()
    if request.method == 'POST':
        can_edit = 1 if request.form.get('can_edit_thesis') == 'on' else 0
        new_password = (request.form.get('password') or '').strip()
        password_hash = generate_password_hash(new_password) if new_password else generate_password_hash(reg_number)

        if user:
            db.execute(
                'UPDATE users SET can_edit_thesis = ?, password_hash = ? WHERE id = ?',
                (can_edit, password_hash, user['id']),
            )
        else:
            db.execute(
                'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, ?)',
                (reg_number, password_hash, 'student', student['name'], student['email'], can_edit),
            )
        db.commit()
        flash('Student access updated. Password reset to the provided value or default reg number if left blank.', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_student_permissions.html', student=dict(student), user=user)


@app.route('/admin/seed-student-login')
@login_required(role='admin')
def seed_student_login():
    db = get_db()
    students = db.execute('SELECT reg_number, name, email FROM students').fetchall()
    for student in students:
        exists = db.execute('SELECT 1 FROM users WHERE username = ? AND role = ?', (student['reg_number'], 'student')).fetchone()
        if not exists:
            db.execute(
                'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, 0)',
                (student['reg_number'], generate_password_hash(student['reg_number']), 'student', student['name'], student['email']),
            )
        else:
            db.execute(
                'UPDATE users SET password_hash = ?, full_name = ?, email = ? WHERE username = ? AND role = ?',
                (generate_password_hash(student['reg_number']), student['name'], student['email'], student['reg_number'], 'student'),
            )
    db.commit()
    flash('Student login accounts seeded and password hashes refreshed.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/setup-admin')
def setup_admin():
    db = get_db()
    ensure_default_admin(db)
    db.commit()
    return 'Admin user created. Please <a href="/login">login</a>.'


# ── Student registration ───────────────────────────────────────────────────

@app.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        reg_number = (request.form.get('reg_number') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        full_name = normalize_name(request.form.get('full_name') or '')
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not reg_number or not email or not full_name or not password:
            flash('Please complete all fields.', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('register.html')

        db = get_db()
        student = db.execute(
            'SELECT * FROM students WHERE reg_number = ? AND email = ?',
            (reg_number, email),
        ).fetchone()

        if not student:
            flash('No matching student record was found. Use your registered registration number and email address.', 'error')
            return render_template('register.html')

        existing_user = db.execute(
            'SELECT * FROM users WHERE username = ? AND role = ?',
            (reg_number, 'student'),
        ).fetchone()
        if existing_user:
            flash('This student account already exists. Please log in instead.', 'error')
            return redirect(url_for('login'))

        db.execute(
            'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, 0)',
            (reg_number, generate_password_hash(password), 'student', full_name, email),
        )
        db.commit()
        flash('Student account created successfully. You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# ── Admin routes to create student profiles ─────────────────────────────────

@app.route('/admin/students/add', methods=('GET', 'POST'))
@login_required(role='admin')
def admin_add_students():
    db = get_db()
    if request.method == 'POST':
        bulk_text = (request.form.get('bulk_students') or '').strip()
        rows_added = 0
        rows_skipped = 0

        if bulk_text:
            lines = [line.strip() for line in bulk_text.splitlines() if line.strip()]
            for line in lines:
                parts = [p.strip() for p in re.split(r'[;,\t|]+', line)]
                if len(parts) >= 3:
                    name, reg_number, email = parts[0], parts[1], parts[2]
                elif len(parts) == 2:
                    name, reg_number = parts
                    email = ''
                else:
                    rows_skipped += 1
                    continue

                if not reg_number or not email:
                    rows_skipped += 1
                    continue

                existing = db.execute('SELECT 1 FROM students WHERE reg_number = ?', (reg_number,)).fetchone()
                if existing:
                    rows_skipped += 1
                    continue

                try:
                    db.execute(
                        'INSERT INTO students (reg_number, email, name, entry_year, gender, cgpa) VALUES (?, ?, ?, ?, ?, ?)',
                        (reg_number, email, name, 2024, 'Not Set', 0.0),
                    )
                    user_exists = db.execute('SELECT 1 FROM users WHERE username = ? AND role = ?', (reg_number, 'student')).fetchone()
                    if not user_exists:
                        db.execute(
                            'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, 0)',
                            (reg_number, generate_password_hash(reg_number), 'student', name, email),
                        )
                    rows_added += 1
                except Exception:
                    rows_skipped += 1
        else:
            name = normalize_name(request.form.get('name') or '')
            reg_number = (request.form.get('reg_number') or '').strip()
            email = (request.form.get('email') or '').strip().lower()

            if not name or not reg_number or not email:
                flash('Please fill in all fields for a student profile.', 'error')
                return render_template('admin_add_students.html')

            existing = db.execute('SELECT 1 FROM students WHERE reg_number = ?', (reg_number,)).fetchone()
            if existing:
                flash('A student with that registration number already exists.', 'error')
                return render_template('admin_add_students.html')

            db.execute(
                'INSERT INTO students (reg_number, email, name, entry_year, gender, cgpa) VALUES (?, ?, ?, ?, ?, ?)',
                (reg_number, email, name, 2024, 'Not Set', 0.0),
            )
            user_exists = db.execute('SELECT 1 FROM users WHERE username = ? AND role = ?', (reg_number, 'student')).fetchone()
            if not user_exists:
                db.execute(
                    'INSERT INTO users (username, password_hash, role, full_name, email, can_edit_thesis) VALUES (?, ?, ?, ?, ?, 0)',
                    (reg_number, generate_password_hash(reg_number), 'student', name, email),
                )
            rows_added = 1

        db.commit()
        flash(f'Added {rows_added} student profile(s). Skipped {rows_skipped}. Default student password is their registration number.', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_add_students.html')


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if not os.path.exists(app.config['DATABASE']):
        init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

DROP TABLE IF EXISTS theses;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS supervisors;
DROP TABLE IF EXISTS otp_store;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    full_name TEXT,
    email TEXT,
    can_edit_thesis INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE supervisors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL
);

CREATE TABLE students (
    reg_number TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    entry_year INTEGER NOT NULL,
    gender TEXT NOT NULL,
    cgpa REAL
);

CREATE TABLE theses (
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
    -- Extended research fields (from proposed database table)
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
    --
    submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_reg_number) REFERENCES students (reg_number)
);

-- Seed Supervisors
INSERT INTO supervisors (name, email, department) VALUES
('Prof. A. Nwachukwu',   'a.nwachukwu@unn.edu.ng',   'Pharmaceutical and Medicinal Chemistry'),
('Dr. B. Okafor',        'b.okafor@unn.edu.ng',        'Pharmaceutical and Medicinal Chemistry'),
('Prof. C. Eze',         'c.eze@unn.edu.ng',           'Pharmaceutical Microbiology and Biotechnology'),
('Dr. D. Okeke',         'd.okeke@unn.edu.ng',         'Pharmaceutics'),
('Prof. E. Udo',         'e.udo@unn.edu.ng',           'Pharmaceutical Technology and Industrial Pharmacy'),
('Dr. F. Obi',           'f.obi@unn.edu.ng',           'Pharmacognosy and Environmental Medicine'),
('Prof. G. Ani',         'g.ani@unn.edu.ng',           'Pharmacology and Toxicology'),
('Dr. H. Kalu',          'h.kalu@unn.edu.ng',          'Clinical Pharmacy and Pharmacy Management');

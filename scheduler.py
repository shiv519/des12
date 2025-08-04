import mysql.connector
import random

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root1234",
    "database": "timetable_db"
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# ---------- DB CONNECTION ----------
def get_connection(include_db=True):
    cfg = DB_CONFIG.copy()
    if not include_db:
        cfg.pop("database", None)
    return mysql.connector.connect(**cfg)

def init_db():
    # Create DB if not exists
    conn = get_connection(include_db=False)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
    conn.commit()
    conn.close()

    conn = get_connection()
    cur = conn.cursor()

    # Teachers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_name VARCHAR(255),
            subject VARCHAR(255),
            grades VARCHAR(255)
        )
    """)
    # Sections
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            id INT AUTO_INCREMENT PRIMARY KEY,
            grade VARCHAR(50),
            section_name VARCHAR(10)
        )
    """)
    # Subjects
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INT AUTO_INCREMENT PRIMARY KEY,
            subject_name VARCHAR(255),
            grade VARCHAR(50),
            periods_per_week INT
        )
    """)
    # Colors
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subject_colors (
            subject_name VARCHAR(255) PRIMARY KEY,
            color_code VARCHAR(7)
        )
    """)
    # Timetable
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teacher_busy_periods (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT,
            period_number INT,
            day_of_week VARCHAR(10),
            grade VARCHAR(50),
            section VARCHAR(10),
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        )
    """)

    # Ensure section column exists
    cur.execute("SHOW COLUMNS FROM teacher_busy_periods LIKE 'section'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE teacher_busy_periods ADD COLUMN section VARCHAR(10)")

    conn.commit()
    conn.close()

# ---------- COLOR HELPERS ----------
def get_random_pastel():
    r = lambda: random.randint(150, 255)
    return f'#{r():02x}{r():02x}{r():02x}'

def get_contrasting_text_color(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
    brightness = (r*299 + g*587 + b*114) / 1000
    return '#000000' if brightness > 150 else '#FFFFFF'

def ensure_subject_color(subject_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT color_code FROM subject_colors WHERE subject_name=%s", (subject_name,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    color = get_random_pastel()
    cur.execute("INSERT INTO subject_colors (subject_name, color_code) VALUES (%s, %s)",
                (subject_name, color))
    conn.commit()
    conn.close()
    return color

def get_subject_colors():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT subject_name, color_code FROM subject_colors")
    colors = {name: code for name, code in cur.fetchall()}
    conn.close()
    return colors

# ---------- DATA HELPERS ----------
def add_section(grade, section_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO sections (grade, section_name) VALUES (%s, %s)", (grade, section_name))
    conn.commit()
    conn.close()

def get_sections_for_grade(grade):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT section_name FROM sections WHERE grade=%s", (grade,))
    sections = [r[0] for r in cur.fetchall()]
    conn.close()
    return sections

def get_teachers_for_grade(grade):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, teacher_name, subject FROM teachers WHERE FIND_IN_SET(%s, grades)", (grade,))
    teachers = cur.fetchall()
    conn.close()
    return teachers

def get_subjects_for_grade(grade):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT subject_name, periods_per_week FROM subjects WHERE grade=%s", (grade,))
    subs = cur.fetchall()
    conn.close()
    return subs

def clear_timetable_for_grade_section(grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM teacher_busy_periods WHERE grade=%s AND section=%s", (grade, section))
    conn.commit()
    conn.close()

def get_day_assignments(day, grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT tbp.period_number, t.teacher_name, t.subject
        FROM teacher_busy_periods tbp
        JOIN teachers t ON tbp.teacher_id = t.id
        WHERE tbp.day_of_week=%s AND tbp.grade=%s AND tbp.section=%s
        ORDER BY tbp.period_number
    """, (day, grade, section))
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- TIMETABLE GENERATION ----------
def generate_timetable(grade, section, absent_teachers_per_day):
    teachers = get_teachers_for_grade(grade)
    subjects = get_subjects_for_grade(grade)
    if not teachers or not subjects:
        return False

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT teacher_id, day_of_week, period_number FROM teacher_busy_periods")
    busy_slots = set(cur.fetchall())

    clear_timetable_for_grade_section(grade, section)

    periods_per_day = 8
    max_daily_load = 5
    max_subject_per_day = 2

    teacher_daily_load = {tid: {day: 0 for day in WEEKDAYS} for tid, _, _ in teachers}
    timetable_grid = {day: {p: None for p in range(1, periods_per_day + 1)} for day in WEEKDAYS}
    subject_count_per_day = {day: {} for day in WEEKDAYS}

    # FIX: Assign exactly one teacher per subject for this section
    subject_teacher_map = {}
    for subject, _ in subjects:
        available_teachers = [t for t in teachers if t[2] == subject]
        if available_teachers:
            subject_teacher_map[subject] = random.choice(available_teachers)  # fixed teacher for this section

    subject_slots = []
    for subject, total_periods in subjects:
        ensure_subject_color(subject)
        subject_slots.extend([subject] * total_periods)
    random.shuffle(subject_slots)

    for subject in subject_slots:
        placed = False
        days = WEEKDAYS[:]
        random.shuffle(days)
        for day in days:
            if subject_count_per_day[day].get(subject, 0) >= max_subject_per_day:
                continue
            periods = list(timetable_grid[day].keys())
            random.shuffle(periods)
            for period_num in periods:
                if timetable_grid[day][period_num] is not None:
                    continue

                # Use fixed teacher for this subject
                if subject not in subject_teacher_map:
                    continue
                t_id, t_name, _ = subject_teacher_map[subject]

                if t_name in absent_teachers_per_day.get(day, []):
                    continue
                if teacher_daily_load[t_id][day] >= max_daily_load:
                    continue
                if (t_id, day, period_num) in busy_slots:
                    continue

                timetable_grid[day][period_num] = (t_id, subject)
                teacher_daily_load[t_id][day] += 1
                subject_count_per_day[day][subject] = subject_count_per_day[day].get(subject, 0) + 1
                busy_slots.add((t_id, day, period_num))
                placed = True
                break
            if placed:
                break

    for day, periods in timetable_grid.items():
        for period_num, assignment in periods.items():
            if assignment:
                t_id, subject = assignment
                cur.execute("""
                    INSERT INTO teacher_busy_periods (teacher_id, period_number, day_of_week, grade, section)
                    VALUES (%s, %s, %s, %s, %s)
                """, (t_id, period_num, day, grade, section))

    conn.commit()
    conn.close()
    return True

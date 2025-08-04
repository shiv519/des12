import streamlit as st
import pandas as pd
import sqlite3
import random
import os
from io import BytesIO

# ---------- DB SETUP ----------
DB_FILE = "timetable.db"

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_name TEXT,
            subject TEXT,
            grades TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teacher_busy_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            grade TEXT,
            section TEXT,
            period_number INTEGER,
            day_of_week TEXT,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT,
            grade TEXT,
            section TEXT,
            periods_per_week INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subject_colors (
            subject_name TEXT PRIMARY KEY,
            color_code TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS grade_section_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT,
            section TEXT,
            days TEXT
        )
    """)
    conn.commit()
    conn.close()

# ---------- COLORS ----------
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
    cur.execute("SELECT color_code FROM subject_colors WHERE subject_name=?", (subject_name,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    color = get_random_pastel()
    cur.execute("INSERT INTO subject_colors (subject_name, color_code) VALUES (?, ?)",
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

# ---------- FETCH ----------
def get_teachers_for_grade(grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, teacher_name, subject FROM teachers WHERE grades LIKE ?", (f"%{grade}-{section}%",))
    teachers = cur.fetchall()
    conn.close()
    return teachers

def get_subjects_for_grade(grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT subject_name, periods_per_week FROM subjects WHERE grade=? AND section=?", (grade, section))
    subs = cur.fetchall()
    conn.close()
    return subs

def clear_timetable_for_grade(grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM teacher_busy_periods
        WHERE grade=? AND section=?
    """, (grade, section))
    conn.commit()
    conn.close()

def get_school_days(grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT days FROM grade_section_days WHERE grade=? AND section=?", (grade, section))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0].split(',')
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# ---------- TIMETABLE GENERATION ----------
def generate_timetable(grade, section, absent_teachers_per_day):
    teachers = get_teachers_for_grade(grade, section)
    subjects = get_subjects_for_grade(grade, section)
    school_days = get_school_days(grade, section)
    if not teachers or not subjects:
        return False

    clear_timetable_for_grade(grade, section)
    conn = get_connection()
    cur = conn.cursor()

    periods_per_day = 8
    max_daily_load = 5
    timetable_grid = {day: {p: None for p in range(1, periods_per_day+1)} for day in school_days}
    teacher_daily_load = {tid: {day: 0 for day in school_days} for tid, _, _ in teachers}
    subject_daily_count = {day: {} for day in school_days}

    # Ensure Games exists
    if not any(s[0].lower() == "games" for s in subjects):
        subjects.append(("Games", 1))
        ensure_subject_color("Games")

    # Fill with all subjects
    subject_slots = []
    for subject, total_periods in subjects:
        ensure_subject_color(subject)
        subject_slots.extend([subject] * total_periods)
    random.shuffle(subject_slots)

    # Place each subject
    for subject in subject_slots:
        placed = False
        for day in random.sample(school_days, len(school_days)):
            # Max 2 same subject/day
            if subject_daily_count[day].get(subject, 0) >= 2:
                continue

            available_teachers = [t for t in teachers if t[2] == subject and
                                  t[1] not in absent_teachers_per_day.get(day, []) and
                                  teacher_daily_load[t[0]][day] < max_daily_load]

            if subject.lower() == "games":
                available_teachers += [t for t in teachers if t[2].lower() == "games"]

            if not available_teachers and subject.lower() != "games":
                # Fallback to Games if no teacher
                subject = "Games"
                ensure_subject_color("Games")
                available_teachers = [t for t in teachers if t[2].lower() == "games"]

            if not available_teachers:
                continue

            for period_num in random.sample(range(1, periods_per_day+1), periods_per_day):
                if timetable_grid[day][period_num] is None:
                    t_id, t_name, _ = random.choice(available_teachers)
                    timetable_grid[day][period_num] = (t_id, subject)
                    teacher_daily_load[t_id][day] += 1
                    subject_daily_count[day][subject] = subject_daily_count[day].get(subject, 0) + 1
                    placed = True
                    break
            if placed:
                break

    # Save to DB
    for day, periods in timetable_grid.items():
        for period_num, assignment in periods.items():
            if assignment:
                t_id, subject = assignment
                cur.execute("""
                    INSERT INTO teacher_busy_periods (teacher_id, grade, section, period_number, day_of_week)
                    VALUES (?, ?, ?, ?, ?)
                """, (t_id, grade, section, period_num, day))
    conn.commit()
    conn.close()
    return True

def get_day_assignments(day, grade, section):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT tbp.period_number, t.teacher_name, t.subject
        FROM teacher_busy_periods tbp
        JOIN teachers t ON tbp.teacher_id = t.id
        WHERE tbp.day_of_week=? AND tbp.grade=? AND tbp.section=?
        ORDER BY tbp.period_number
    """, (day, grade, section))
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- STREAMLIT ----------
init_db()
st.set_page_config(page_title="School Timetable", layout="wide")
tabs = st.tabs(["📥 Setup", "📅 School Days", "🚫 Absentees", "📅 Timetable"])

# Setup tab
with tabs[0]:
    st.header("Upload or Add Teachers & Subjects")
    teacher_file = st.file_uploader("Upload Teachers CSV", type=["csv"], key="teacher_csv")
    if teacher_file:
        df = pd.read_csv(teacher_file)
        conn = get_connection()
        cur = conn.cursor()
        for _, row in df.iterrows():
            cur.execute("INSERT INTO teachers (teacher_name, subject, grades) VALUES (?, ?, ?)",
                        (row["teacher_name"], row["subject"], row["grades"]))
        conn.commit()
        conn.close()
        st.success("Teachers uploaded!")

    with st.form("add_teacher"):
        t_name = st.text_input("Teacher Name", key="add_teacher_name")
        t_sub = st.text_input("Subject", key="add_teacher_subject")
        t_grades = st.text_input("Grades-Sections (e.g., 10-A,10-B)", key="add_teacher_grades")
        if st.form_submit_button("Add Teacher"):
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO teachers (teacher_name, subject, grades) VALUES (?, ?, ?)",
                        (t_name, t_sub, t_grades))
            conn.commit()
            conn.close()
            st.success("Teacher added!")

    with st.form("add_subject"):
        s_name = st.text_input("Subject Name", key="add_subject_name")
        s_grade = st.text_input("Grade", key="add_subject_grade")
        s_section = st.text_input("Section", key="add_subject_section")
        s_periods = st.number_input("Periods per week", 1, 14, key="add_subject_periods")
        if st.form_submit_button("Add/Update Subject"):
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO subjects (subject_name, grade, section, periods_per_week)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(subject_name) DO UPDATE SET periods_per_week=excluded.periods_per_week
            """, (s_name, s_grade, s_section, s_periods))
            conn.commit()
            conn.close()
            ensure_subject_color(s_name)
            st.success("Subject added/updated!")

# School Days tab
with tabs[1]:
    st.header("Set School Days for Each Grade-Section")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT grade, section FROM subjects")
    gs_list = cur.fetchall()
    conn.close()
    for grade, section in gs_list:
        current_days = get_school_days(grade, section)
        selected_days = st.multiselect(f"{grade}-{section} Days", 
                                       ["Monday","Tuesday","Wednesday","Thursday","Friday"],
                                       default=current_days, key=f"days_{grade}_{section}")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM grade_section_days WHERE grade=? AND section=?", (grade, section))
        cur.execute("INSERT INTO grade_section_days (grade, section, days) VALUES (?, ?, ?)",
                    (grade, section, ",".join(selected_days)))
        conn.commit()
        conn.close()

# Absentees tab
absent_teachers = {}
with tabs[2]:
    st.header("Mark Absent Teachers")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT teacher_name FROM teachers")
    all_teachers = [r[0] for r in cur.fetchall()]
    conn.close()
    for day in ["Monday","Tuesday","Wednesday","Thursday","Friday"]:
        absent = st.multiselect(f"{day} Absentees", all_teachers, key=f"absent_{day}")
        absent_teachers[day] = absent

# Timetable tab
with tabs[3]:
    st.header("Generate / View Timetable")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT grade, section FROM subjects")
    grades = [f"{g}-{s}" for g, s in cur.fetchall()]
    conn.close()
    if grades:
        selected_gs = st.selectbox("Select Grade-Section", grades, key="tt_grade_section")
        grade, section = selected_gs.split("-")
        if st.button("Generate Timetable", key="btn_generate_tt"):
            if generate_timetable(grade, section, absent_teachers):
                st.success("Timetable generated!")

        subject_colors = get_subject_colors()
        for day in get_school_days(grade, section):
            st.subheader(day)
            assignments = get_day_assignments(day, grade, section)
            cols = st.columns(8)
            for i, col in enumerate(cols, start=1):
                match = next((a for a in assignments if a[0] == i), None)
                if match:
                    _, teacher, subject = match
                    color = subject_colors.get(subject, "#eeeeee")
                    text_color = get_contrasting_text_color(color)
                    col.markdown(
                        f"<div style='background-color:{color};color:{text_color};padding:8px;border-radius:5px;text-align:center;'>"
                        f"{teacher}<br><b>{subject}</b></div>",
                        unsafe_allow_html=True
                    )
                else:
                    col.markdown(
                        "<div style='background-color:#f0f0f0;padding:8px;border-radius:5px;text-align:center;'>Free</div>",
                        unsafe_allow_html=True
                    )

import streamlit as st
import pandas as pd
import scheduler

scheduler.init_db()

st.set_page_config(page_title="School Timetable", layout="wide")

tabs = st.tabs(["📥 Setup", "🚫 Absentees", "📅 Timetable"])

# ---------- PAGE 1: SETUP ----------
with tabs[0]:
    st.header("Teacher Management")
    teacher_file = st.file_uploader("Upload Teachers CSV (teacher_name,subject,grades)", type=["csv"])
    if teacher_file:
        df = pd.read_csv(teacher_file)
        conn = scheduler.get_connection()
        cur = conn.cursor()
        for _, row in df.iterrows():
            cur.execute("INSERT INTO teachers (teacher_name, subject, grades) VALUES (%s, %s, %s)",
                        (row["teacher_name"], row["subject"], row["grades"]))
        conn.commit()
        conn.close()
        st.success("Teachers uploaded!")

    st.subheader("Add Teacher Manually")
    with st.form("manual_teacher_form"):
        t_name = st.text_input("Teacher Name")
        t_subject = st.text_input("Subject")
        t_grades = st.text_input("Grades (comma-separated)")
        submitted = st.form_submit_button("Add Teacher")
        if submitted and t_name and t_subject and t_grades:
            conn = scheduler.get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO teachers (teacher_name, subject, grades) VALUES (%s, %s, %s)",
                        (t_name, t_subject, t_grades))
            conn.commit()
            conn.close()
            st.success(f"Added {t_name}")

    st.markdown("---")
    st.header("Subject Management")
    with st.form("subject_form"):
        sub_name = st.text_input("Subject Name")
        grade = st.text_input("Grade")
        periods = st.number_input("Periods per week", min_value=1, max_value=14)
        submitted = st.form_submit_button("Add Subject")
        if submitted and sub_name and grade:
            conn = scheduler.get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO subjects (subject_name, grade, periods_per_week) VALUES (%s, %s, %s)",
                        (sub_name, grade, periods))
            conn.commit()
            conn.close()
            scheduler.ensure_subject_color(sub_name)
            st.success(f"Added {sub_name} for Grade {grade}")

    st.subheader("Update Subject Periods")
    with st.form("update_subject_form"):
        grade_sel = st.text_input("Grade for Subject")
        sub_sel = st.text_input("Subject Name to Update")
        new_periods = st.number_input("New Periods per week", min_value=1, max_value=14)
        submitted = st.form_submit_button("Update Periods")
        if submitted and grade_sel and sub_sel:
            conn = scheduler.get_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE subjects SET periods_per_week=%s WHERE grade=%s AND subject_name=%s
            """, (new_periods, grade_sel, sub_sel))
            conn.commit()
            conn.close()
            st.success(f"Updated {sub_sel} in Grade {grade_sel}")

    st.markdown("---")
    st.header("Section Management")
    with st.form("section_form"):
        sec_grade = st.text_input("Grade for Section")
        sec_name = st.text_input("Section Name")
        submitted = st.form_submit_button("Add Section")
        if submitted and sec_grade and sec_name:
            scheduler.add_section(sec_grade, sec_name)
            st.success(f"Added Section {sec_name} to Grade {sec_grade}")

# ---------- PAGE 2: ABSENTEES ----------
absent_teachers = {}
with tabs[1]:
    st.header("Mark Absent Teachers")
    conn = scheduler.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT teacher_name FROM teachers")
    all_teachers = [r[0] for r in cur.fetchall()]
    conn.close()

    for day in scheduler.WEEKDAYS:
        absent = st.multiselect(f"{day} Absentees", all_teachers)
        absent_teachers[day] = absent

# ---------- PAGE 3: TIMETABLE ----------
with tabs[2]:
    st.header("Generate & View Timetable")
    conn = scheduler.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT grade FROM subjects")
    grades = [r[0] for r in cur.fetchall()]
    conn.close()

    if grades:
        selected_grade = st.selectbox("Select Grade", grades)
        sections = scheduler.get_sections_for_grade(selected_grade)
        if sections:
            selected_section = st.selectbox("Select Section", sections)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Auto Generate Timetable"):
                    success = scheduler.generate_timetable(selected_grade, selected_section, absent_teachers)
                    if success:
                        st.success("Timetable generated!")
                        st.rerun()
            with col2:
                if st.button("View Existing Timetable"):
                    st.info("Showing existing timetable...")

            subject_colors = scheduler.get_subject_colors()
            for day in scheduler.WEEKDAYS:
                st.subheader(f"{day} - Grade {selected_grade} Section {selected_section}")
                assignments = scheduler.get_day_assignments(day, selected_grade, selected_section)
                cols = st.columns(8)
                for i, col in enumerate(cols, start=1):
                    match = next((a for a in assignments if a[0] == i), None)
                    if match:
                        _, teacher, subject = match
                        color = subject_colors.get(subject, "#eeeeee")
                        text_color = scheduler.get_contrasting_text_color(color)
                        col.markdown(
                            f"<div style='background-color:{color};color:{text_color};"
                            f"padding:8px;border-radius:5px;text-align:center;'>"
                            f"{teacher}<br><b>{subject}</b></div>",
                            unsafe_allow_html=True
                        )
                    else:
                        col.markdown(
                            "<div style='background-color:#f0f0f0;padding:8px;border-radius:5px;text-align:center;'>Free</div>",
                            unsafe_allow_html=True
                        )
        else:
            st.warning("No sections found for this grade. Please add sections in Setup.")
    else:
        st.warning("No grades found. Please add subjects first.")

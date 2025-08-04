import streamlit as st
import pandas as pd
import sqlite3
import random
import os
from io import BytesIO

DB_FILE = "timetable.db"
ALL_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# --- DB SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_name TEXT, subject TEXT, grades TEXT, sections TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_name TEXT, grade TEXT, periods_per_week INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subject_colors (
        subject_name TEXT PRIMARY KEY, color_code TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grade TEXT, section TEXT, day_of_week TEXT,
        period_number INTEGER, teacher_id INTEGER, subject TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS school_days (
        grade TEXT, section TEXT, days TEXT,
        PRIMARY KEY (grade, section))""")
    conn.commit()
    conn.close()

def get_conn(): 
    return sqlite3.connect(DB_FILE)

# --- HELPERS ---
def random_pastel():
    r = lambda: random.randint(150, 255)
    return f'#{r():02x}{r():02x}{r():02x}'

def ensure_color(subject):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT color_code FROM subject_colors WHERE subject_name=?",(subject,))
    if not cur.fetchone():
        cur.execute("INSERT INTO subject_colors VALUES(?,?)",(subject, random_pastel()))
    conn.commit(); conn.close()

def get_colors():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT subject_name,color_code FROM subject_colors")
    d = dict(cur.fetchall()); conn.close(); return d

def get_school_days(grade, section):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT days FROM school_days WHERE grade=? AND section=?",(grade,section))
    row = cur.fetchone(); conn.close()
    if row and row[0]:
        return row[0].split(",")
    return ALL_WEEKDAYS[:]  # default all days

# --- GENERATE TIMETABLE ---
def generate_timetable(grade, section):
    days = get_school_days(grade, section)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM timetable WHERE grade=? AND section=?", (grade, section))
    cur.execute("SELECT id,teacher_name,subject FROM teachers WHERE grades LIKE ? AND sections LIKE ?", 
                (f"%{grade}%", f"%{section}%"))
    teachers = cur.fetchall()
    cur.execute("SELECT subject_name,periods_per_week FROM subjects WHERE grade=?", (grade,))
    subjects = cur.fetchall()
    games_teachers = [t for t in teachers if t[2].lower()=="games"]
    if not teachers or not subjects: conn.close(); return False

    teacher_daily = {t[0]:{d:0 for d in days} for t in teachers}
    timetable = {d:{p:None for p in range(1,9)} for d in days}
    subj_day_count = {d:{} for d in days}

    subj_teacher_map = {}
    for sub,_ in subjects:
        tlist = [t for t in teachers if t[2]==sub]
        if tlist: subj_teacher_map[sub]=random.choice(tlist)
        ensure_color(sub)

    # ensure 1 games/week
    if games_teachers:
        day_for_games = random.choice(days)
        pnum = random.randint(1,8)
        gteach = random.choice(games_teachers)
        timetable[day_for_games][pnum]=(gteach[0],"Games")
        teacher_daily[gteach[0]][day_for_games]+=1
        subj_day_count[day_for_games]["Games"]=1

    # slots
    slots=[]
    for sub,count in subjects:
        slots += [sub]*count
    random.shuffle(slots)

    for sub in slots:
        placed=False
        for day in random.sample(days,len(days)):
            if subj_day_count[day].get(sub,0)>=2: continue
            for p in random.sample(range(1,9),8):
                if timetable[day][p]: continue
                tid,tname,_=subj_teacher_map[sub]
                if teacher_daily[tid][day]>=5: continue
                cur.execute("""SELECT 1 FROM timetable WHERE day_of_week=? 
                               AND period_number=? AND teacher_id=?""", (day,p,tid))
                if cur.fetchone(): continue
                timetable[day][p]=(tid,sub)
                teacher_daily[tid][day]+=1
                subj_day_count[day][sub]=subj_day_count[day].get(sub,0)+1
                placed=True; break
            if placed: break

    for day in days:
        for p,(tid,sub) in timetable[day].items():
            if tid:
                cur.execute("""INSERT INTO timetable 
                            (grade,section,day_of_week,period_number,teacher_id,subject) 
                            VALUES (?,?,?,?,?,?)""",
                            (grade,section,day,p,tid,sub))
    conn.commit(); conn.close(); return True

# --- VIEW WITH SUBSTITUTIONS ---
def get_day_assignments(day, grade, section, absentees):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT t.period_number, tc.teacher_name, tc.subject
                   FROM timetable t
                   JOIN teachers tc ON t.teacher_id=tc.id
                   WHERE t.day_of_week=? AND t.grade=? AND t.section=?""",
                   (day,grade,section))
    rows = cur.fetchall(); conn.close()
    games_teachers = [r[1] for r in rows if r[2].lower()=="games"]
    for i,(p,teach,sub) in enumerate(rows):
        if teach in absentees.get(day,[]):
            conn = get_conn(); cur = conn.cursor()
            cur.execute("""SELECT teacher_name FROM teachers 
                           WHERE subject=? AND teacher_name NOT IN ({seq})""".format(
                           seq=",".join("?"*len(absentees.get(day,[]))) or "?"),
                           ([sub] + absentees.get(day,[])) if absentees.get(day,[]) else [sub])
            repl = cur.fetchone()
            conn.close()
            if repl: rows[i]=(p,repl[0],sub)
            else: rows[i]=(p, random.choice(games_teachers) if games_teachers else "", "Games")
    return rows

# --- STREAMLIT UI ---
st.set_page_config(layout="wide")
init_db()
tabs = st.tabs(["Setup","Absentees","Timetable"])

with tabs[0]:
    st.header("Manage Teachers")
    file=st.file_uploader("Upload CSV (teacher_name,subject,grades,sections)",type="csv")
    if file:
        df=pd.read_csv(file); conn=get_conn(); cur=conn.cursor()
        for _,r in df.iterrows():
            cur.execute("INSERT INTO teachers (teacher_name,subject,grades,sections) VALUES (?,?,?,?)",
                        (r.teacher_name,r.subject,r.grades,r.sections))
        conn.commit(); conn.close(); st.success("Uploaded")
    with st.form("addteach"):
        tn=st.text_input("Name"); sb=st.text_input("Subject"); gr=st.text_input("Grades"); sec=st.text_input("Sections")
        if st.form_submit_button("Add") and tn and sb: 
            conn=get_conn(); cur=conn.cursor()
            cur.execute("INSERT INTO teachers (teacher_name,subject,grades,sections) VALUES (?,?,?,?)",(tn,sb,gr,sec))
            conn.commit(); conn.close(); st.success("Added")

    st.subheader("Manage Subjects")
    with st.form("addsub"):
        sn=st.text_input("Subject Name"); gr=st.text_input("Grade"); per=st.number_input("Periods/week",1,14)
        if st.form_submit_button("Add/Update") and sn and gr:
            conn=get_conn(); cur=conn.cursor()
            cur.execute("""INSERT OR REPLACE INTO subjects 
                        (id,subject_name,grade,periods_per_week) 
                        VALUES ((SELECT id FROM subjects WHERE subject_name=? AND grade=?),?,?,?)""",
                        (sn,gr,sn,gr,per))
            conn.commit(); conn.close(); ensure_color(sn); st.success("Saved")

    st.subheader("Manage School Days")
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT DISTINCT grade FROM subjects"); grades_for_days=[r[0] for r in cur.fetchall()]
    conn.close()
    if grades_for_days:
        g=st.selectbox("Grade", grades_for_days)
        sec=st.text_input("Section for Days","A")
        current_days = get_school_days(g,sec)
        selected_days = st.multiselect("Select School Days", ALL_WEEKDAYS, default=current_days)
        if st.button("Save School Days"):
            conn=get_conn(); cur=conn.cursor()
            cur.execute("""INSERT OR REPLACE INTO school_days 
                        (grade,section,days) VALUES (?,?,?)""",(g,sec,",".join(selected_days)))
            conn.commit(); conn.close(); st.success("Saved")

with tabs[1]:
    st.header("Mark Absentees")
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT DISTINCT teacher_name FROM teachers"); all_teachers=[r[0] for r in cur.fetchall()]
    conn.close()
    absentees={}; 
    for d in ALL_WEEKDAYS: absentees[d]=st.multiselect(f"{d} Absentees",all_teachers)

with tabs[2]:
    st.header("Generate/View Timetable")
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT DISTINCT grade FROM subjects"); grades=[r[0] for r in cur.fetchall()]
    conn.close()
    if grades:
        g=st.selectbox("Grade",grades)
        sec=st.text_input("Section","A")
        if st.button("Generate Timetable"): 
            if generate_timetable(g,sec): st.success("Generated"); st.experimental_rerun()
        colors=get_colors()
        days = get_school_days(g, sec)
        for d in days:
            st.subheader(d)
            ass=get_day_assignments(d,g,sec,absentees)
            cols=st.columns(8)
            for i,col in enumerate(cols,1):
                match=next((a for a in ass if a[0]==i),None)
                if match:
                    _,t,s=match; color = "#90EE90" if s.lower()=="games" else colors.get(s,"#ddd")
                    col.markdown(f"<div style='background:{color};padding:8px;border-radius:5px;text-align:center;'>{t}<br><b>{s}</b></div>",unsafe_allow_html=True)
                else:
                    col.markdown("<div style='background:#f0f0f0;padding:8px;border-radius:5px;text-align:center;'>Free</div>",unsafe_allow_html=True)

        # Filtered Excel download
        if st.button("Download as Excel"):
            days = get_school_days(g, sec)
            conn = get_conn()
            df = pd.read_sql_query("""
                SELECT day_of_week, period_number, subject, 
                       (SELECT teacher_name FROM teachers WHERE id = timetable.teacher_id) AS teacher
                FROM timetable 
                WHERE grade=? AND section=? 
                ORDER BY CASE day_of_week
                    WHEN 'Monday' THEN 1
                    WHEN 'Tuesday' THEN 2
                    WHEN 'Wednesday' THEN 3
                    WHEN 'Thursday' THEN 4
                    WHEN 'Friday' THEN 5
                END, period_number
            """, conn, params=(g, sec))
            conn.close()
            df = df[df['day_of_week'].isin(days)]
            buf = BytesIO()
            df.to_excel(buf, index=False, sheet_name=f"{g}{sec}")
            buf.seek(0)
            st.download_button(
                "Download Excel",
                data=buf,
                file_name=f"{g}{sec}_timetable.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

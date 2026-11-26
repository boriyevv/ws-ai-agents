"""Eski Excel jadvalini bir martada bazaga yuklash.

Ishga tushirish (loyiha papkasida):
    python -m scripts.import_excel fayl_nomi.xlsx

Kutiladigan format: HAR BIR VARAQ = bitta guruh. Ustunlar: № | Ism-familiya | To'lov | sana ustunlari (+ yoki -).
Skript har bir varaq uchun savol beradi (guruh kunlari, vaqti, o'qituvchi), keyin hammasini saqlaydi.
Qayta ishga tushirsangiz, mavjud o'quvchilar takrorlanmaydi.
"""
import re
import secrets
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta

import openpyxl
import psycopg
from psycopg.rows import dict_row

from app import config
from app.core import fuzzy, norm, roll_forward, today

PREFIX_DAYS = {"du": 1, "se": 2, "ch": 3, "pa": 4, "ju": 5, "sh": 6, "ya": 7}
ABSENT = {"-", "–", "—", "−", "н", "n"}


def ask(prompt, default=None):
    s = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return s or (default or "")


def parse_days(s):
    out = set()
    for tok in re.split(r"[\s,;/]+", s.lower()):
        if tok[:2] in PREFIX_DAYS:
            out.add(PREFIX_DAYS[tok[:2]])
    return sorted(out)


def parse_time_range(s):
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*[-–]\s*(\d{1,2})[:.](\d{2})\s*", s)
    if not m:
        return None
    a, b, c, d = map(int, m.groups())
    return time(a, b), time(c, d)


def cell_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})", s)
        if m:
            try:
                return date(today().year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    return None


def to_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else 0
    return 0


def parse_sheet(ws):
    rows = list(ws.iter_rows(values_only=True))
    header_idx = None
    for i, r in enumerate(rows[:15]):
        if any(isinstance(c, str) and "ism" in norm(c) for c in r):
            header_idx = i
            break
    if header_idx is None:
        return None
    header = rows[header_idx]
    name_col = next(i for i, c in enumerate(header) if isinstance(c, str) and "ism" in norm(c))
    pay_col = next((i for i, c in enumerate(header)
                    if isinstance(c, str) and any(k in norm(c) for k in ("tolov", "summa", "oplata"))), None)
    date_cols = [(i, cell_date(c)) for i, c in enumerate(header) if i > name_col and cell_date(c)]
    students = []
    for r in rows[header_idx + 1:]:
        name = r[name_col] if name_col < len(r) else None
        if not isinstance(name, str) or not name.strip() or name.strip().isdigit():
            continue
        pay = to_int(r[pay_col]) if pay_col is not None and pay_col < len(r) else 0
        marks = {}
        for i, d in date_cols:
            v = r[i] if i < len(r) else None
            if isinstance(v, str):
                v = v.strip().lower()
                if v == "+":
                    marks[d] = "present"
                elif v in ABSENT:
                    marks[d] = "absent"
        students.append({"name": name.strip(), "pay": pay, "marks": marks})
    return {"dates": [d for _, d in date_cols], "students": students}


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, prepare_threshold=None) as conn:
        cur = conn.cursor()
        cur.execute("select id, name from branches order by name")
        branches = cur.fetchall()
        print("\nFiliallar:")
        for i, b in enumerate(branches, 1):
            print(f"  {i}. {b['name']}")
        branch = branches[int(ask("Qaysi filialga yuklaymiz? (raqam)", "1")) - 1]

        for ws in wb.worksheets:
            data = parse_sheet(ws)
            print(f"\n=== Varaq: {ws.title} ===")
            if not data or not data["students"]:
                print("  Ism-familiya ustuni yoki o'quvchilar topilmadi, o'tkazib yuborildi.")
                continue
            print(f"  O'quvchilar: {len(data['students'])}, sana ustunlari: {len(data['dates'])}")
            if ask("  Bu guruhni yuklaymizmi? (ha/yo'q)", "ha").lower() not in ("ha", "h", "yes", "y"):
                continue

            cur.execute("select id from groups where branch_id=%s and lower(name)=lower(%s)", (branch["id"], ws.title))
            g = cur.fetchone()
            if g:
                gid = g["id"]
                print("  Guruh bazada bor, shunga qo'shamiz.")
            else:
                subject = ask("  Fan", ws.title)
                days = []
                while not days:
                    days = parse_days(ask("  Dars kunlari (masalan: du, chor, juma)"))
                rng = None
                while not rng:
                    rng = parse_time_range(ask("  Dars vaqti (masalan: 14:00-16:00)", "14:00-16:00"))
                teacher_name = ask("  O'qituvchi ismi (bo'sh qoldirsa ham bo'ladi)")
                room_name = ask("  Xona nomi (bo'sh qoldirsa ham bo'ladi)")
                teacher_id = room_id = None
                if teacher_name:
                    cur.execute("select t.id, s.full_name from teachers t join staff s on s.id=t.staff_id")
                    hits = fuzzy(teacher_name, [(r["id"], r["full_name"]) for r in cur.fetchall()], limit=1, min_score=0.8)
                    if hits:
                        teacher_id = hits[0][1]
                    else:
                        cur.execute("insert into staff (full_name, role, invite_code) values (%s,'teacher',%s) "
                                    "returning id", (teacher_name, secrets.token_hex(5)))
                        sid = cur.fetchone()["id"]
                        cur.execute("insert into staff_branch_access (staff_id, branch_id) values (%s,%s)",
                                    (sid, branch["id"]))
                        cur.execute("insert into teachers (staff_id, subject) values (%s,%s) returning id",
                                    (sid, subject))
                        teacher_id = cur.fetchone()["id"]
                if room_name:
                    cur.execute("select id from rooms where branch_id=%s and lower(name)=lower(%s)",
                                (branch["id"], room_name))
                    r = cur.fetchone()
                    if not r:
                        cur.execute("insert into rooms (branch_id, name) values (%s,%s) returning id",
                                    (branch["id"], room_name))
                        r = cur.fetchone()
                    room_id = r["id"]
                try:
                    cur.execute(
                        "insert into groups (branch_id, name, subject, teacher_id, room_id, days, start_time, end_time) "
                        "values (%s,%s,%s,%s,%s,%s::smallint[],%s,%s) returning id",
                        (branch["id"], ws.title, subject, teacher_id, room_id, days, rng[0], rng[1]))
                    gid = cur.fetchone()["id"]
                except psycopg.Error as e:
                    conn.rollback()
                    print(f"  XATO: guruh yaratilmadi ({str(e).splitlines()[0]}). Varaq o'tkazib yuborildi.")
                    continue
            cur.execute("select days from groups where id=%s", (gid,))

            fees = Counter(s["pay"] for s in data["students"] if s["pay"] > 0)
            default_fee = fees.most_common(1)[0][0] if fees else ""
            fee = to_int(ask("  Oylik to'lov summasi (so'm)", str(default_fee) if default_fee else None))

            cur.execute("select id, full_name from students where branch_id=%s and status <> 'left'", (branch["id"],))
            existing = [(r["id"], r["full_name"]) for r in cur.fetchall()]
            n_new = n_att = n_pay = 0
            first_date = min(data["dates"]) if data["dates"] else today()
            for s in data["students"]:
                present_days = sorted(d for d, v in s["marks"].items() if v == "present")
                start = present_days[0] if present_days else first_date
                hit = fuzzy(s["name"], existing, limit=1, min_score=0.95)
                if hit:
                    sid = hit[0][1]
                else:
                    cur.execute("insert into students (branch_id, full_name, joined_on) values (%s,%s,%s) returning id",
                                (branch["id"], s["name"], start))
                    sid = cur.fetchone()["id"]
                    existing.append((sid, s["name"]))
                    n_new += 1
                cur.execute("select id from enrollments where student_id=%s and group_id=%s", (sid, gid))
                e = cur.fetchone()
                if e:
                    eid = e["id"]
                else:
                    # Exceldagi "To'lov" ustuni = joriy 30 kunlik tsikl uchun to'lov deb olinadi.
                    # Oldingi oylar uchun qarz yozilmaydi (Excelda ular haqida ma'lumot yo'q).
                    cs, _, _ = roll_forward(start, True, -10**6, today())
                    paid = s["pay"] > 0
                    cur.execute(
                        "insert into enrollments (student_id, group_id, joined_on, cycle_start, cycle_paid, "
                        "unpaid_cycles, monthly_fee) values (%s,%s,%s,%s,%s,0,%s) returning id",
                        (sid, gid, start, cs, paid, fee or None))
                    eid = cur.fetchone()["id"]
                    if s["pay"] > 0:
                        cur.execute(
                            "insert into payments (enrollment_id, amount, paid_on, period_start, period_end, note) "
                            "values (%s,%s,%s,%s,%s,'Excel importi')",
                            (eid, s["pay"], cs, cs, cs + timedelta(days=29)))
                        n_pay += 1
                for d, status in s["marks"].items():
                    cur.execute(
                        "insert into attendance (enrollment_id, lesson_date, status) values (%s,%s,%s::attendance_status) "
                        "on conflict (enrollment_id, lesson_date) do nothing", (eid, d, status))
                    n_att += 1
            print(f"  Yangi o'quvchilar: {n_new}, davomat yozuvlari: {n_att}, to'lovlar: {n_pay}")
            if ask("  Saqlaymizmi? (ha/yo'q)", "ha").lower() in ("ha", "h", "yes", "y"):
                conn.commit()
                print("  Saqlandi.")
            else:
                conn.rollback()
                print("  Bekor qilindi.")
    print("\nTayyor. Endi botga yozing: 'qarzdorlar kimlar?'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Ishlatish: python -m scripts.import_excel fayl_nomi.xlsx")
    main(sys.argv[1])

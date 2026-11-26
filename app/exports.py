"""Tizimdagi ma'lumotni Excel faylga nusxalash."""
import calendar
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import db
from .core import DAY_SHORT, fmt_money, payment_state, today, invite_link

STATE_UZ = {"paid": "to'langan", "not_yet": "hali vaqti emas", "window": "to'lov oynasi ochiq",
            "overdue": "qarz"}


def _book(title, header, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for i, h in enumerate(header, 1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 45)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def build(kind, bids, group=None, month=None, can_finance=True):
    """Qaytaradi: (fayl_nomi, bytes)"""
    t = today()
    if kind == "students":
        rows = await db.q(
            """select s.full_name, b.name as branch, coalesce(string_agg(distinct g.name, ', '), '') as groups,
                      s.status::text as status, s.joined_on,
                      coalesce(string_agg(distinct p.phone, ', '), '') as phones
               from students s join branches b on b.id = s.branch_id
               left join enrollments e on e.student_id = s.id and e.status <> 'left'
               left join groups g on g.id = e.group_id
               left join student_parents sp on sp.student_id = s.id
               left join parents p on p.id = sp.parent_id
               where s.branch_id = any(%s) group by s.id, b.name order by b.name, s.full_name""", bids)
        data = [[i + 1, r["full_name"], r["branch"], r["groups"], r["status"], r["joined_on"], r["phones"]]
                for i, r in enumerate(rows)]
        return f"oquvchilar_{t}.xlsx", _book("O'quvchilar", ["№", "Ism-familiya", "Filial", "Guruhlar", "Holat",
                                                           "Qo'shilgan sana", "Ota-ona telefoni"], data)

    if kind == "payments":
        y, m = (month or t.strftime("%Y-%m")).split("-")
        first = date(int(y), int(m), 1)
        last = date(int(y), int(m), calendar.monthrange(int(y), int(m))[1])
        rows = await db.q(
            """select p.paid_on, s.full_name, g.name as group_name, b.name as branch, p.amount, p.method
               from payments p join enrollments e on e.id = p.enrollment_id
               join students s on s.id = e.student_id join groups g on g.id = e.group_id
               join branches b on b.id = g.branch_id
               where g.branch_id = any(%s) and p.paid_on between %s and %s order by p.paid_on""", bids, first, last)
        data = [[r["paid_on"], r["full_name"], r["group_name"], r["branch"], int(r["amount"]), r["method"]]
                for r in rows]
        data.append(["", "JAMI", "", "", sum(int(r["amount"]) for r in rows), ""])
        return f"tolovlar_{y}-{m}.xlsx", _book("To'lovlar", ["Sana", "O'quvchi", "Guruh", "Filial", "Summa",
                                                            "Usul"], data)

    if kind == "debtors":
        from .queries import payment_overview
        rows = [r for r in await payment_overview(bids) if r["state"] in ("overdue", "window")]
        data = [[r["full_name"], r["group_name"], r["branch"], STATE_UZ[r["state"]],
                 int(r["monthly_fee"]) if r["monthly_fee"] else "", r["cycle_start"]] for r in rows]
        return f"qarzdorlar_{t}.xlsx", _book("Qarzdorlar", ["O'quvchi", "Guruh", "Filial", "Holat",
                                                           "Oylik to'lov", "Tsikl boshi"], data)

    if kind == "leads":
        rows = await db.q(
            """select l.created_at::date as sana, l.full_name, l.phone, l.source, l.status::text as status,
                      c.name as campaign, l.note
               from leads l left join campaigns c on c.id = l.campaign_id
               where (l.branch_id = any(%s) or l.branch_id is null) order by l.created_at desc""", bids)
        data = [[r["sana"], r["full_name"], r["phone"], r["source"], r["status"], r["campaign"], r["note"]]
                for r in rows]
        return f"lidlar_{t}.xlsx", _book("Lidlar", ["Sana", "Ism", "Telefon", "Manba", "Holat", "Kampaniya",
                                                    "Izoh"], data)

    if kind == "invite_links":
        rows = await db.q(
            """select s.full_name, s.invite_code,
                      (select string_agg(p.phone, ', ') from student_parents sp join parents p on p.id = sp.parent_id
                       where sp.student_id = s.id) as phones,
                      exists (select 1 from student_parents sp join parents p on p.id = sp.parent_id
                              where sp.student_id = s.id and p.telegram_id is not null) as linked
               from students s where s.branch_id = any(%s) and s.status = 'active' order by s.full_name""", bids)
        data = [[r["full_name"], r["phones"] or "", "ulangan" if r["linked"] else "ULANMAGAN",
                 invite_link("pr", r["invite_code"])] for r in rows]
        return f"ota_ona_havolalari_{t}.xlsx", _book("Havolalar", ["O'quvchi", "Ota-ona telefoni", "Holat",
                                                                  "Telegram havolasi"], data)

    if kind == "attendance_grid":
        if not group:
            raise ValueError("Guruh kerak")
        y, m = (month or t.strftime("%Y-%m")).split("-")
        first = date(int(y), int(m), 1)
        last = date(int(y), int(m), calendar.monthrange(int(y), int(m))[1])
        roster = await db.q(
            """select e.id as eid, s.full_name from enrollments e join students s on s.id = e.student_id
               where e.group_id = %s and e.status <> 'left' order by s.full_name""", group["id"])
        att = await db.q(
            """select a.enrollment_id, a.lesson_date, a.status::text as status
               from attendance a join enrollments e on e.id = a.enrollment_id
               where e.group_id = %s and a.lesson_date between %s and %s""", group["id"], first, last)
        dates = sorted({a["lesson_date"] for a in att})
        cell = {(a["enrollment_id"], a["lesson_date"]): ("+" if a["status"] == "present" else "-") for a in att}
        header = ["№", "Ism-familiya"] + [d.strftime("%d.%m") for d in dates]
        data = [[i + 1, r["full_name"]] + [cell.get((r["eid"], d), "") for d in dates]
                for i, r in enumerate(roster)]
        return f"davomat_{group['name']}_{y}-{m}.xlsx".replace(" ", "_"), _book(group["name"], header, data)

    raise ValueError(f"Noma'lum eksport turi: {kind}")

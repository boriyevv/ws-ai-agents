import { useEffect, useState } from "react";
import { api, fmtDate, money, PAY_STATE, STUDENT_STATUS, todayISO, type Group } from "../api";
import { Badge, Card, CopyText, DataTable, Empty, ExportButton, Field, Loading, Modal, PageHead, useAction, useApp, useLoad } from "../ui";

interface StudentRow { id: string; ism: string; holat: string; filial: string; guruhlar: string; ota_ona_ulangan: boolean }

export default function Students() {
  const { can } = useApp();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const { data, loading, reload } = useLoad(
    () => api<{ oquvchilar: StudentRow[] }>(`/api/students?q=${encodeURIComponent(query)}`), [query]);

  return (
    <div className="stack">
      <PageHead title="O'quvchilar">
        <ExportButton kind="students" label="Excel" />
        <ExportButton kind="invite_links" label="Ota-ona havolalari" />
        {can("add_student") && <button className="primary" onClick={() => setAdding(true)}>+ Yangi o'quvchi</button>}
      </PageHead>
      <Card>
        <input placeholder="Ism bo'yicha qidirish…" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 12 }} />
        {loading && !data ? <Loading /> : !data?.oquvchilar.length ? <Empty>Topilmadi</Empty> : (
          <DataTable<StudentRow> rows={data.oquvchilar} rowKey={(r) => r.id}
            onRow={can("student_profile") ? (r) => setSelected(r.id) : undefined} cols={[
              { key: "ism", label: "Ism-familiya", main: true },
              { key: "guruhlar", label: "Guruhlar", render: (r) => r.guruhlar || "—" },
              { key: "filial", label: "Filial" },
              { key: "holat", label: "Holat", render: (r) => <Badge tone={r.holat === "active" ? "ok" : "warn"}>{STUDENT_STATUS[r.holat] ?? r.holat}</Badge> },
              { key: "ota", label: "Ota-ona", render: (r) => r.ota_ona_ulangan ? <Badge tone="ok">Botda</Badge> : <Badge>Ulanmagan</Badge> },
            ]} />
        )}
      </Card>
      <Modal title="O'quvchi" open={!!selected} onClose={() => { setSelected(null); reload(); }}>
        {selected && <Profile id={selected} />}
      </Modal>
      <Modal title="Yangi o'quvchi" open={adding} onClose={() => setAdding(false)}>
        <AddStudent onDone={(id) => { setAdding(false); reload(); setSelected(id); }} />
      </Modal>
    </div>
  );
}

interface ProfileData {
  id: string; ism: string; holat: string; qoshilgan: string | null; izoh: string | null; ota_ona_havolasi: string;
  ota_ona: { full_name: string | null; phone: string | null; telegramga_ulangan: boolean; relation: string | null }[];
  guruhlar: { group_name: string; cycle_start: string | null; unpaid_cycles: number; status: string; tolov_holati: string; oylik_tolov: number | null }[];
  oxirgi_davomat: { lesson_date: string; status: string; group_name: string }[];
  imtihonlar: { exam_name: string; exam_date: string; score: string; target_score: string | null }[];
  oxirgi_tolovlar?: { paid_on: string; amount: string; group_name: string }[];
}

function Profile({ id }: { id: string }) {
  const { can } = useApp();
  const { data, loading, reload } = useLoad(() => api<ProfileData>(`/api/students/${id}`), [id]);
  if (loading && !data) return <Loading />;
  if (!data) return <Empty />;
  return (
    <div className="stack">
      <div className="row">
        <h2 className="spacer">{data.ism}</h2>
        <Badge tone={data.holat === "active" ? "ok" : "warn"}>{STUDENT_STATUS[data.holat] ?? data.holat}</Badge>
      </div>
      <div className="muted small">Qo'shilgan: {fmtDate(data.qoshilgan)}{data.izoh ? ` · ${data.izoh}` : ""}</div>

      <div>
        <h3>Guruhlar va to'lov holati</h3>
        <div className="list">
          {data.guruhlar.map((g) => {
            const st = PAY_STATE[g.tolov_holati] ?? { text: g.tolov_holati, tone: "" };
            return (
              <div className="list-item" key={g.group_name}>
                <div>{g.group_name}<div className="muted small">Tsikl boshi: {fmtDate(g.cycle_start)}{g.oylik_tolov ? ` · ${money(g.oylik_tolov)}/oy` : ""}</div></div>
                <Badge tone={st.tone}>{st.text}{g.unpaid_cycles > 0 ? ` (${g.unpaid_cycles} oy)` : ""}</Badge>
              </div>
            );
          })}
        </div>
      </div>

      {can("record_payment") && data.holat !== "left" && (
        <PaymentForm studentId={data.id} groups={data.guruhlar.map((g) => g.group_name)} onDone={reload} />
      )}

      <div>
        <h3>Ota-ona</h3>
        {data.ota_ona.length === 0 ? <Empty>Kiritilmagan</Empty> : (
          <div className="list">
            {data.ota_ona.map((p, i) => (
              <div className="list-item" key={i}>
                <span>{p.full_name ?? "—"} {p.relation ? `(${p.relation})` : ""} <span className="muted">{p.phone ?? ""}</span></span>
                {p.telegramga_ulangan ? <Badge tone="ok">Botga ulangan</Badge> : <Badge>Ulanmagan</Badge>}
              </div>
            ))}
          </div>
        )}
        <div className="muted small" style={{ margin: "8px 0 4px" }}>Ota-ona uchun Telegram havolasi (bosganda botga ulanadi):</div>
        <CopyText text={data.ota_ona_havolasi} />
      </div>

      <div className="grid two">
        <div>
          <h3>Oxirgi davomat</h3>
          {data.oxirgi_davomat.length === 0 ? <Empty /> : (
            <div className="list">
              {data.oxirgi_davomat.map((a, i) => (
                <div className="list-item" key={i}>
                  <span className="num">{fmtDate(a.lesson_date)} <span className="muted small">{a.group_name}</span></span>
                  {a.status === "present" ? <Badge tone="ok">Keldi</Badge> : <Badge tone="bad">Kelmadi</Badge>}
                </div>
              ))}
            </div>
          )}
        </div>
        {data.oxirgi_tolovlar && (
          <div>
            <h3>Oxirgi to'lovlar</h3>
            {data.oxirgi_tolovlar.length === 0 ? <Empty /> : (
              <div className="list">
                {data.oxirgi_tolovlar.map((p, i) => (
                  <div className="list-item" key={i}>
                    <span className="num">{fmtDate(p.paid_on)} <span className="muted small">{p.group_name}</span></span>
                    <span className="num">{money(p.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {data.imtihonlar.length > 0 && (
        <div>
          <h3>Imtihonlar</h3>
          <div className="list">
            {data.imtihonlar.map((x, i) => (
              <div className="list-item" key={i}>
                <span>{x.exam_name} <span className="muted small">{fmtDate(x.exam_date)}</span></span>
                <span className="num">{Number(x.score)}{x.target_score ? ` / ${Number(x.target_score)}` : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PaymentForm({ studentId, groups, onDone }: { studentId: string; groups: string[]; onDone: () => void }) {
  const { busy, run } = useAction();
  const [amount, setAmount] = useState("");
  const [group, setGroup] = useState(groups[0] ?? "");
  const [method, setMethod] = useState("naqd");
  const [date, setDate] = useState(todayISO());
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const sum = Number(amount.replace(/\s/g, ""));
    if (!confirm(`${money(sum)} to'lov yozilsinmi?`)) return;
    run(() => api("/api/payments", { body: { student: studentId, amount: sum, group, method, paid_on: date } }), "To'lov yozildi")
      .then((r) => { if (r) { setAmount(""); onDone(); } });
  };
  return (
    <Card title="To'lov qabul qilish" className="soft">
      <form className="form" onSubmit={submit}>
        <Field label="Summa (so'm)"><input required inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="300 000" /></Field>
        {groups.length > 1 && (
          <Field label="Guruh"><select value={group} onChange={(e) => setGroup(e.target.value)}>{groups.map((g) => <option key={g}>{g}</option>)}</select></Field>
        )}
        <Field label="Usul">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="naqd">Naqd</option><option value="karta">Karta</option><option value="o'tkazma">O'tkazma</option>
          </select>
        </Field>
        <Field label="Sana"><input type="date" value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} /></Field>
        <div className="form-actions"><button className="primary" disabled={busy}>Saqlash</button></div>
      </form>
    </Card>
  );
}

function AddStudent({ onDone }: { onDone: (id: string) => void }) {
  const { data } = useLoad(() => api<{ guruhlar: Group[] }>("/api/groups"));
  const { busy, run } = useAction();
  const [f, setF] = useState({ full_name: "", group: "", parent_name: "", parent_phone: "", monthly_fee: "", joined_on: todayISO() });
  const [link, setLink] = useState<{ id: string; url: string } | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  useEffect(() => { if (data?.guruhlar[0] && !f.group) setF((x) => ({ ...x, group: data.guruhlar[0].id })); }, [data, f.group]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(() => api<{ student_id: string; ota_ona_havolasi: string }>("/api/students", {
      body: { ...f, monthly_fee: f.monthly_fee ? Number(f.monthly_fee.replace(/\s/g, "")) : null },
    }), "O'quvchi qo'shildi").then((r) => r && setLink({ id: r.student_id, url: r.ota_ona_havolasi }));
  };

  if (link) return (
    <div className="stack">
      <p>✅ O'quvchi qo'shildi. Quyidagi havolani ota-onaga yuboring: bosganda bot ularni farzandiga bog'laydi.</p>
      <CopyText text={link.url} />
      <div className="form-actions"><button className="primary" onClick={() => onDone(link.id)}>O'quvchi profilini ochish</button></div>
    </div>
  );

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Ism-familiya"><input required value={f.full_name} onChange={set("full_name")} /></Field>
      <Field label="Guruh">
        <select required value={f.group} onChange={set("group")}>
          {data?.guruhlar.map((g) => <option key={g.id} value={g.id}>{g.nom} ({g.filial})</option>)}
        </select>
      </Field>
      <Field label="Ota-ona ismi"><input value={f.parent_name} onChange={set("parent_name")} /></Field>
      <Field label="Ota-ona telefoni"><input value={f.parent_phone} onChange={set("parent_phone")} placeholder="+998 90 123 45 67" /></Field>
      <Field label="Oylik to'lov (bo'sh = guruhdagidek)"><input inputMode="numeric" value={f.monthly_fee} onChange={set("monthly_fee")} /></Field>
      <Field label="Kelgan sana"><input type="date" value={f.joined_on} onChange={set("joined_on")} /></Field>
      <div className="form-actions"><button className="primary" disabled={busy}>Qo'shish</button></div>
    </form>
  );
}

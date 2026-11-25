import { useState } from "react";
import { api, fmtDate } from "../api";
import { Badge, Card, CopyText, DataTable, Empty, Field, Loading, Modal, PageHead, Tabs, useAction, useApp, useLoad } from "../ui";

interface Row { id: string; full_name: string; role: string; botga_ulangan: boolean; filiallar: string; taklif_havolasi: string | null }
const ROLE: Record<string, string> = { owner: "Rahbar", manager: "Manager", admin: "Administrator", teacher: "O'qituvchi" };

export default function Staff() {
  const { can } = useApp();
  const [tab, setTab] = useState<"xodimlar" | "yollash">("xodimlar");
  return (
    <div className="stack">
      <PageHead title="Xodimlar" />
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "xodimlar", label: "Xodimlar" }, { key: "yollash", label: "Yollash", show: can("list_candidates") }]} />
      {tab === "xodimlar" ? <People /> : <Hiring />}
    </div>
  );
}

function People() {
  const { data, loading } = useLoad(() => api<{ xodimlar: Row[] }>("/api/staff"));
  return (
    <>
      <p className="muted" style={{ margin: 0 }}>
        Yangi xodim qo'shish yoki filial ruxsatini o'zgartirish uchun Jimiga ayting, masalan: "Aziz ismli manager
        qo'sh, 1-filial" yoki "Dilnozaga 2-filialni ham ochib ber".
      </p>
      <Card>
        {loading && !data ? <Loading /> : !data?.xodimlar.length ? <Empty /> : (
          <div className="list">
            {data.xodimlar.map((s) => (
              <div className="list-item" key={s.id} style={{ flexWrap: "wrap" }}>
                <div style={{ minWidth: 180, flex: 1 }}>
                  <b>{s.full_name}</b> <span className="muted small">{ROLE[s.role] ?? s.role}</span>
                  <div className="muted small">{s.filiallar}</div>
                </div>
                {s.botga_ulangan ? <Badge tone="ok">Botga ulangan</Badge> : <Badge tone="warn">Ulanmagan</Badge>}
                {s.taklif_havolasi && <div style={{ flexBasis: "100%" }}><CopyText text={s.taklif_havolasi} /></div>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

interface Cand { id: string; full_name: string | null; phone: string | null; vakansiya: string | null; ai_score: number | null; ai_summary: string | null; status: string; interview_at: string | null; sana: string }
interface Vac { id: string; title: string; status: string; sana: string; arizalar: number; havola: string }
const CST: Record<string, string> = { yangi: "", saralandi: "info", suhbat: "warn", qabul: "ok", rad: "bad" };

function Hiring() {
  const { data, loading, reload } = useLoad(() => api<{ nomzodlar: Cand[]; vakansiyalar: Vac[] }>("/api/candidates"));
  const { busy, run } = useAction();
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Cand | null>(null);
  const [when, setWhen] = useState("");
  if (loading && !data) return <Loading />;
  const setStatus = (c: Cand, status: string) => {
    if (!confirm(`${c.full_name}: «${status}». Nomzodga Telegramda xabar boradi. Davom etamizmi?`)) return;
    run(() => api(`/api/candidates/${c.id}`, { body: { status, interview_at: when ? when.replace("T", " ") : null } }), "Saqlandi")
      .then(() => { setSel(null); reload(); });
  };
  return (
    <div className="stack">
      <Card title="Vakansiyalar" action={<button className="primary" onClick={() => setOpen(true)}>+ Vakansiya</button>}>
        {!data?.vakansiyalar.length ? <Empty>Vakansiya yo'q. Jimiga ham aytish mumkin: «Jimi, IELTS o'qituvchisi uchun vakansiya och».</Empty> : (
          <div className="list">
            {data.vakansiyalar.map((v) => (
              <div className="list-item" key={v.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className="row"><b className="spacer">{v.title}</b><Badge tone={v.status === "ochiq" ? "ok" : ""}>{v.status}</Badge>
                  <span className="muted small">{v.arizalar} ariza</span></div>
                <CopyText text={v.havola} />
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card title="Nomzodlar">
        <DataTable<Cand> rows={data?.nomzodlar ?? []} empty="Hali ariza yo'q" rowKey={(c) => c.id} onRow={setSel} cols={[
          { key: "full_name", label: "Nomzod", main: true, render: (c) => <span>{c.full_name ?? "—"} <span className="muted small">{c.phone}</span></span> },
          { key: "vakansiya", label: "Vakansiya", render: (c) => c.vakansiya ?? "—" },
          { key: "ai", label: "AI baho", render: (c) => c.ai_score ? <Badge tone={c.ai_score >= 7 ? "ok" : c.ai_score >= 5 ? "warn" : "bad"}>{c.ai_score}/10</Badge> : "—" },
          { key: "status", label: "Holat", render: (c) => <Badge tone={CST[c.status]}>{c.status}</Badge> },
          { key: "sana", label: "Sana", render: (c) => fmtDate(c.sana) },
        ]} />
      </Card>
      <Modal title="Yangi vakansiya" open={open} onClose={() => setOpen(false)}>
        <NewVacancy onDone={() => { setOpen(false); reload(); }} />
      </Modal>
      <Modal title={sel?.full_name ?? "Nomzod"} open={!!sel} onClose={() => setSel(null)}>
        {sel && (
          <div className="stack">
            <div className="muted">{sel.vakansiya} · {sel.phone}</div>
            <Card className="soft"><b>AI xulosa ({sel.ai_score ?? "?"}/10):</b><div className="pre">{sel.ai_summary ?? "—"}</div></Card>
            <Field label="Suhbat vaqti"><input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
            <div className="form-actions">
              <button className="danger" disabled={busy} onClick={() => setStatus(sel, "rad")}>Rad etish</button>
              <button disabled={busy} onClick={() => setStatus(sel, "suhbat")}>Suhbatga chaqirish</button>
              <button className="primary" disabled={busy} onClick={() => setStatus(sel, "qabul")}>Qabul qilish</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function NewVacancy({ onDone }: { onDone: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({ title: "", description: "", requirements: "", questions: "" });
  const [link, setLink] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  if (link) return (
    <div className="stack">
      <p>✅ Vakansiya ochildi. Ariza havolasini e'lon ostiga qo'ying: nomzod botda savollarga javob beradi, AI uni baholab sizga yuboradi.</p>
      <CopyText text={link} />
      <div className="form-actions"><button className="primary" onClick={onDone}>Yopish</button></div>
    </div>
  );
  return (
    <form className="form" onSubmit={(e) => {
      e.preventDefault();
      run(() => api<{ ariza_havolasi: string }>("/api/vacancies", { body: { ...f, questions: f.questions.split("\n") } }))
        .then((r) => r && setLink(r.ariza_havolasi));
    }}>
      <Field label="Lavozim" full><input required value={f.title} onChange={set("title")} placeholder="Ingliz tili o'qituvchisi (IELTS 7+)" /></Field>
      <Field label="Ish sharoiti" full><textarea value={f.description} onChange={set("description")} /></Field>
      <Field label="Talablar" full><textarea value={f.requirements} onChange={set("requirements")} /></Field>
      <Field label="Nomzodga savollar (har qatorda bitta; bo'sh = standart)" full><textarea value={f.questions} onChange={set("questions")} /></Field>
      <div className="form-actions"><button className="primary" disabled={busy}>Ochish</button></div>
    </form>
  );
}

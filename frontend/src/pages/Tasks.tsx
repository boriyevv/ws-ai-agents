import { useMemo, useState } from "react";
import { api, fmtDate } from "../api";
import { Badge, Card, DataTable, Field, Loading, Modal, PageHead, Tabs, useAction, useApp, useLoad } from "../ui";

interface Task {
  id: string; text: string; holat: string; holat_kod: string; due_at: string | null; created_at: string;
  kimga: string; kimdan: string | null; menga: boolean; men_bergan: boolean; kechikkan: boolean; delivered: boolean;
}
type Scope = "hammasi" | "menga" | "men_bergan";
const TONE: Record<string, string> = { sent: "info", seen: "warn", done: "ok", cancelled: "" };

const fmtDT = (s: string | null) => (s ? `${fmtDate(s)} ${new Date(s).toTimeString().slice(0, 5)}` : "—");

export default function Tasks() {
  const { can } = useApp();
  const [scope, setScope] = useState<Scope>("hammasi");
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [adding, setAdding] = useState(false);
  const { data, loading, reload } = useLoad(() => api<{ vazifalar: Task[] }>(`/api/tasks?scope=${scope}&only_open=${onlyOpen}`), [scope, onlyOpen]);
  const { busy, run } = useAction();

  const setStatus = (t: Task, status: string) =>
    run(() => api(`/api/tasks/${t.id}`, { body: { status } }), status === "done" ? "Bajarildi deb belgilandi" : "Bekor qilindi").then(reload);

  return (
    <div className="stack">
      <PageHead title="Vazifalar">
        <label className="check"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Faqat ochiqlar</label>
        {can("send_task") && <button className="primary" onClick={() => setAdding(true)}>+ Vazifa berish</button>}
      </PageHead>
      <p className="muted" style={{ margin: 0 }}>
        Jimiga og'zaki ham aytish mumkin: «Jimi, Zufar bugun darsini 1 soat ertaroq boshlasin». Xodim Telegramda
        «✅ Bajarildi» tugmasini bosadi, sizga xabar keladi; muddati o'tsa eslatma boradi.
      </p>
      <Card>
        <Tabs<Scope> value={scope} onChange={setScope} tabs={[
          { key: "hammasi", label: "Hammasi" }, { key: "menga", label: "Menga" },
          { key: "men_bergan", label: "Men berganlar", show: can("send_task") }]} />
        <div style={{ marginTop: 12 }}>
          {loading && !data ? <Loading /> : (
            <DataTable<Task> rows={data?.vazifalar ?? []} empty="Vazifa yo'q" rowKey={(t) => t.id} cols={[
              { key: "text", label: "Vazifa", main: true, render: (t) => <span className="pre">{t.text}</span> },
              { key: "kimga", label: "Kimga" },
              { key: "kimdan", label: "Kimdan" },
              { key: "due", label: "Muddat", render: (t) => <span className={t.kechikkan ? "down" : ""}>{fmtDT(t.due_at)}</span> },
              { key: "holat", label: "Holat", render: (t) => (
                <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                  <Badge tone={t.kechikkan ? "bad" : TONE[t.holat_kod]}>{t.kechikkan ? "muddati o'tdi" : t.holat}</Badge>
                  {!t.delivered && <Badge tone="warn">botga ulanmagan</Badge>}
                </span>) },
              { key: "act", label: "", right: true, render: (t) => (
                <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                  {t.menga && ["sent", "seen"].includes(t.holat_kod) &&
                    <button className="primary" disabled={busy} onClick={() => setStatus(t, "done")}>Bajarildi</button>}
                  {t.men_bergan && ["sent", "seen"].includes(t.holat_kod) &&
                    <button className="danger" disabled={busy} onClick={() => setStatus(t, "cancelled")}>Bekor</button>}
                </span>) },
            ]} />
          )}
        </div>
      </Card>
      <Modal title="Vazifa berish" open={adding} onClose={() => setAdding(false)}>
        <NewTask onDone={() => { setAdding(false); reload(); }} />
      </Modal>
    </div>
  );
}

interface Person { id: string; ism: string; rol: string; botda: boolean }
const ROLE_UZ: Record<string, string> = { manager: "Manager", admin: "Admin", teacher: "O'qituvchi" };

function NewTask({ onDone }: { onDone: () => void }) {
  const { data } = useLoad(() => api<{ xodimlar: Person[] }>("/api/task-recipients"));
  const { busy, run } = useAction();
  const [mode, setMode] = useState<"odam" | "rol">("odam");
  const [picked, setPicked] = useState<string[]>([]);
  const [role, setRole] = useState("teacher");
  const [text, setText] = useState("");
  const [due, setDue] = useState("");
  const [q, setQ] = useState("");
  const people = useMemo(() => (data?.xodimlar ?? []).filter((p) => p.ism.toLowerCase().includes(q.toLowerCase())), [data, q]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const who = mode === "odam" ? `${picked.length} kishiga` : `${role === "all" ? "hammaga" : ROLE_UZ[role] + "larga"}`;
    if (!confirm(`Vazifa ${who} Telegram orqali yuborilsinmi?`)) return;
    run(() => api<{ yuborildi: string[]; yetkazilmadi_botga_ulanmagan: string[] }>("/api/tasks", {
      body: { text, due: due ? due.replace("T", " ") : null, recipients: mode === "odam" ? picked : null, role: mode === "rol" ? role : null },
    })).then((r) => {
      if (!r) return;
      alert(`Yuborildi: ${r.yuborildi.join(", ") || "—"}` + (r.yetkazilmadi_botga_ulanmagan.length ? `\nBotga ulanmagan: ${r.yetkazilmadi_botga_ulanmagan.join(", ")}` : ""));
      onDone();
    });
  };

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Vazifa matni" full>
        <textarea required value={text} onChange={(e) => setText(e.target.value)} placeholder="Bugun darsingizni 1 soat ertaroq, 13:00 da boshlang." />
      </Field>
      <Field label="Muddat (ixtiyoriy)"><input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      <Field label="Kimga">
        <select value={mode} onChange={(e) => setMode(e.target.value as "odam" | "rol")}>
          <option value="odam">Tanlangan xodimlarga</option><option value="rol">Rol bo'yicha hammaga</option>
        </select>
      </Field>
      {mode === "rol" ? (
        <Field label="Rol">
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="teacher">Hamma o'qituvchilar</option><option value="admin">Hamma adminlar</option>
            <option value="manager">Hamma managerlar</option><option value="all">Hamma xodimlar</option>
          </select>
        </Field>
      ) : (
        <div className="full">
          <input placeholder="Xodimni qidirish…" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 8 }} />
          <div className="list" style={{ maxHeight: 260, overflowY: "auto" }}>
            {people.map((p) => (
              <label key={p.id} className="list-item check" style={{ cursor: "pointer" }}>
                <span><input type="checkbox" checked={picked.includes(p.id)}
                  onChange={(e) => setPicked(e.target.checked ? [...picked, p.id] : picked.filter((x) => x !== p.id))} /> {p.ism}
                  <span className="muted small"> · {ROLE_UZ[p.rol] ?? p.rol}</span></span>
                {!p.botda && <Badge tone="warn">botda emas</Badge>}
              </label>
            ))}
          </div>
        </div>
      )}
      <div className="form-actions">
        <button className="primary" disabled={busy || !text.trim() || (mode === "odam" && !picked.length)}>Yuborish</button>
      </div>
    </form>
  );
}

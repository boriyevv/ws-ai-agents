import { useState } from "react";
import { api, fmtDate, LEAD_STATUS, money, pct } from "../api";
import { Badge, Card, DataTable, Empty, ExportButton, Field, Loading, Modal, PageHead, useAction, useApp, useLoad } from "../ui";

interface Lead { id: string; sana: string; full_name: string | null; phone: string | null; source: string | null; status: string; kampaniya: string | null; note: string | null }
interface Stats {
  manbalar_boyicha: { source: string; jami: number; sinov: number; oquvchi_boldi: number; rad_etdi: number }[];
  kampaniyalar: { name: string; platform: string | null; sarf: number; lidlar: number; oquvchi_boldi: number; bir_lid_narxi: number | null; bir_oquvchi_narxi: number | null }[];
}

const TONE: Record<string, string> = { new: "info", contacted: "", trial: "warn", enrolled: "ok", rejected: "bad" };

export default function Leads() {
  const { can } = useApp();
  const [status, setStatus] = useState("");
  const [adding, setAdding] = useState(false);
  const { data, loading, reload } = useLoad(() => api<{ lidlar: Lead[]; statistika?: Stats }>(`/api/leads?status=${status}`), [status]);
  const { run } = useAction();

  const change = (l: Lead, s: string) =>
    run(() => api(`/api/leads/${l.id}`, { body: { status: s, kind: "panel", note: `Holat: ${LEAD_STATUS[s]}` } }), "Yangilandi").then(reload);

  return (
    <div className="stack">
      <PageHead title="Lidlar">
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
          <option value="">Hammasi</option>
          {Object.entries(LEAD_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <ExportButton kind="leads" label="Excel" />
        {can("add_lead") && <button className="primary" onClick={() => setAdding(true)}>+ Yangi lid</button>}
      </PageHead>

      {data?.statistika && <StatsCards s={data.statistika} />}

      <Card title="Ro'yxat">
        {loading && !data ? <Loading /> : !data?.lidlar.length ? <Empty>Lid yo'q</Empty> : (
          <DataTable<Lead> rows={data.lidlar} rowKey={(l) => l.id} cols={[
            { key: "ism", label: "Ism", main: true, render: (l) => <span>{l.full_name ?? "—"}{l.note && <div className="muted small">{l.note}</div>}</span> },
            { key: "sana", label: "Sana", render: (l) => fmtDate(l.sana) },
            { key: "tel", label: "Telefon", render: (l) => <a href={`tel:${l.phone}`}>{l.phone}</a> },
            { key: "manba", label: "Manba", render: (l) => `${l.source ?? "—"}${l.kampaniya ? ` · ${l.kampaniya}` : ""}` },
            { key: "holat", label: "Holat", render: (l) => can("update_lead") ? (
              <select value={l.status} onChange={(e) => change(l, e.target.value)} style={{ width: "auto", minHeight: 34 }}>
                {Object.entries(LEAD_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>) : <Badge tone={TONE[l.status]}>{LEAD_STATUS[l.status]}</Badge> },
          ]} />
        )}
      </Card>

      <Modal title="Yangi lid" open={adding} onClose={() => setAdding(false)}>
        <AddLead onDone={() => { setAdding(false); reload(); }} />
      </Modal>
    </div>
  );
}

function StatsCards({ s }: { s: Stats }) {
  return (
    <div className="grid two">
      <Card title="Manbalar (30 kun)">
        {!s.manbalar_boyicha.length ? <Empty /> : (
          <DataTable rows={s.manbalar_boyicha} cols={[
            { key: "source", label: "Manba", main: true },
            { key: "jami", label: "Lid", right: true, render: (m) => String(m.jami) },
            { key: "sinov", label: "Sinov", right: true, render: (m) => String(m.sinov) },
            { key: "oq", label: "O'quvchi", right: true, render: (m) => String(m.oquvchi_boldi) },
            { key: "k", label: "Konversiya", right: true, render: (m) => pct(m.jami ? m.oquvchi_boldi / m.jami : null) },
          ]} />
        )}
      </Card>
      <Card title="Kampaniyalar">
        {!s.kampaniyalar.length ? <Empty>Reklama xarajati kiritilmagan</Empty> : (
          <DataTable rows={s.kampaniyalar} cols={[
            { key: "name", label: "Kampaniya", main: true, render: (c) => <span>{c.name} <span className="muted small">{c.lidlar} lid · {c.oquvchi_boldi} o'quvchi</span></span> },
            { key: "sarf", label: "Sarf", right: true, render: (c) => money(c.sarf) },
            { key: "lid", label: "1 lid", right: true, render: (c) => money(c.bir_lid_narxi) },
            { key: "oq", label: "1 o'quvchi", right: true, render: (c) => money(c.bir_oquvchi_narxi) },
          ]} />
        )}
      </Card>
    </div>
  );
}

function AddLead({ onDone }: { onDone: () => void }) {
  const { me } = useApp();
  const { busy, run } = useAction();
  const [f, setF] = useState({ full_name: "", phone: "", source: "instagram_forma", branch: me.branches.find((b) => b.active)?.name ?? "", campaign: "", note: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="form" onSubmit={(e) => { e.preventDefault(); run(() => api("/api/leads", { body: f }), "Lid qo'shildi").then((r) => r && onDone()); }}>
      <Field label="Ism"><input value={f.full_name} onChange={set("full_name")} /></Field>
      <Field label="Telefon"><input required value={f.phone} onChange={set("phone")} /></Field>
      <Field label="Manba">
        <select value={f.source} onChange={set("source")}>
          <option value="instagram_forma">Instagram forma</option><option value="instagram_direct">Instagram direct</option>
          <option value="telegram">Telegram</option><option value="tavsiya">Tavsiya</option><option value="boshqa">Boshqa</option>
        </select>
      </Field>
      <Field label="Filial">
        <select value={f.branch} onChange={set("branch")}>{me.branches.map((b) => <option key={b.id}>{b.name}</option>)}</select>
      </Field>
      <Field label="Kampaniya (ixtiyoriy)"><input value={f.campaign} onChange={set("campaign")} /></Field>
      <Field label="Izoh" full><textarea value={f.note} onChange={set("note")} /></Field>
      <div className="form-actions"><button className="primary" disabled={busy}>Qo'shish</button></div>
    </form>
  );
}

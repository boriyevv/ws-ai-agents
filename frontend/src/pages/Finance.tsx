import { useState } from "react";
import { api, money, moneyShort, todayISO } from "../api";
import { Card, Empty, Field, Kpi, Loading, Modal, PageHead, useAction, useApp, useLoad } from "../ui";

interface Fin {
  davr: string; tushum_jami: number; xarajat_jami: number; reklama_xarajati: number; sof_foyda_taxminan: number;
  tushum_filiallar: { filial: string; summa: number; tolovlar_soni: number }[];
  xarajat_toifalar: { toifa: string; summa: number }[];
}

const PERIODS: Record<string, string> = {
  this_month: "Shu oy", last_month: "O'tgan oy", last_30_days: "So'nggi 30 kun", this_week: "Shu hafta", today: "Bugun",
};

export default function Finance() {
  const { can } = useApp();
  const [period, setPeriod] = useState("this_month");
  const [adding, setAdding] = useState(false);
  const { data, loading, reload } = useLoad(() => api<Fin>(`/api/finance?period=${period}`), [period]);
  const maxExp = Math.max(1, ...(data?.xarajat_toifalar.map((x) => x.summa) ?? [1]));
  return (
    <div className="stack">
      <PageHead title="Moliya">
        <select value={period} onChange={(e) => setPeriod(e.target.value)} style={{ width: "auto" }}>
          {Object.entries(PERIODS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {can("add_expense") && <button className="primary" onClick={() => setAdding(true)}>+ Xarajat</button>}
      </PageHead>
      {loading && !data ? <Loading /> : data && (
        <>
          <div className="grid kpis">
            <Kpi label="Tushum" value={moneyShort(data.tushum_jami)} hint={money(data.tushum_jami)} />
            <Kpi label="Xarajat" value={moneyShort(data.xarajat_jami)} hint={money(data.xarajat_jami)} />
            <Kpi label="Reklama" value={moneyShort(data.reklama_xarajati)} hint={money(data.reklama_xarajati)} />
            <Kpi label="Sof foyda (taxminan)" value={moneyShort(data.sof_foyda_taxminan)} tone={data.sof_foyda_taxminan < 0 ? "alert" : "good"} />
          </div>
          <div className="grid two">
            <Card title="Tushum filiallar bo'yicha">
              {!data.tushum_filiallar.length ? <Empty>Bu davrda to'lov yo'q</Empty> : (
                <div className="list">{data.tushum_filiallar.map((b) => (
                  <div className="list-item" key={b.filial}><span>{b.filial} <span className="muted small">{b.tolovlar_soni} ta to'lov</span></span><b className="num">{money(b.summa)}</b></div>
                ))}</div>
              )}
            </Card>
            <Card title="Xarajatlar toifalar bo'yicha">
              {!data.xarajat_toifalar.length ? <Empty>Xarajat kiritilmagan</Empty> : (
                <div className="stack" style={{ gap: 10 }}>{data.xarajat_toifalar.map((x) => (
                  <div key={x.toifa}>
                    <div className="row"><span className="spacer">{x.toifa}</span><span className="num">{money(x.summa)}</span></div>
                    <div className="bar"><span style={{ width: `${(x.summa / maxExp) * 100}%` }} /></div>
                  </div>
                ))}</div>
              )}
            </Card>
          </div>
          <p className="muted small" style={{ margin: 0 }}>Davr: {data.davr}. Sof foyda = tushum − xarajat − reklama (maosh va ijara kiritilgan bo'lsa, hisobga olinadi).</p>
        </>
      )}
      <Modal title="Xarajat yozish" open={adding} onClose={() => setAdding(false)}>
        <AddExpense onDone={() => { setAdding(false); reload(); }} />
      </Modal>
    </div>
  );
}

function AddExpense({ onDone }: { onDone: () => void }) {
  const { me } = useApp();
  const { busy, run } = useAction();
  const [f, setF] = useState({ amount: "", category: "ijara", note: "", spent_on: todayISO(), branch: me.branches.find((b) => b.active)?.name ?? "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const amount = Number(f.amount.replace(/\s/g, ""));
    if (!confirm(`${money(amount)} xarajat yozilsinmi?`)) return;
    run(() => api("/api/expenses", { body: { ...f, amount } }), "Xarajat yozildi").then((r) => r && onDone());
  };
  return (
    <form className="form" onSubmit={submit}>
      <Field label="Summa (so'm)"><input required inputMode="numeric" value={f.amount} onChange={set("amount")} /></Field>
      <Field label="Toifa">
        <select value={f.category} onChange={set("category")}>
          {["ijara", "maosh", "kommunal", "reklama", "jihoz", "boshqa"].map((c) => <option key={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="Filial"><select value={f.branch} onChange={set("branch")}>{me.branches.map((b) => <option key={b.id}>{b.name}</option>)}</select></Field>
      <Field label="Sana"><input type="date" value={f.spent_on} onChange={set("spent_on")} /></Field>
      <Field label="Izoh" full><input value={f.note} onChange={set("note")} /></Field>
      <div className="form-actions"><button className="primary" disabled={busy}>Saqlash</button></div>
    </form>
  );
}

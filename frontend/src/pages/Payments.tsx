import { useState } from "react";
import { api, fmtDate, money, todayISO } from "../api";
import { Badge, Card, DataTable, ExportButton, Loading, PageHead, useApp, useLoad } from "../ui";

interface Row { ism: string; guruh: string; filial: string; oylik_tolov: number | null; tolanmagan_tsikllar: number; tsikl_boshi: string | null }
interface Debtors { qarzdorlar: Row[]; tolov_oynasi_ochiq: Row[] }

function Table({ rows, debt }: { rows: Row[]; debt?: boolean }) {
  return (
    <DataTable<Row> rows={rows} empty={debt ? "Qarzdor yo'q 🎉" : "Hozir yo'q"} cols={[
      { key: "ism", label: "O'quvchi", main: true, render: (r) => <span>{r.ism} <span className="muted small">{r.filial}</span></span> },
      { key: "guruh", label: "Guruh" },
      { key: "tsikl", label: "Tsikl boshi", render: (r) => fmtDate(r.tsikl_boshi) },
      { key: "oylik", label: "Oylik", right: true, render: (r) => money(r.oylik_tolov) },
      ...(debt ? [{ key: "qarz", label: "Qarz", render: (r: Row) => <Badge tone="bad">{Math.max(r.tolanmagan_tsikllar, 1)} oy</Badge> }] : []),
    ]} />
  );
}

export default function Payments() {
  const { can } = useApp();
  const [month, setMonth] = useState(todayISO().slice(0, 7));
  const { data, loading } = useLoad(() => api<Debtors>("/api/debtors"));
  return (
    <div className="stack">
      <PageHead title="To'lovlar">
        <ExportButton kind="debtors" label="Qarzdorlar (Excel)" />
        {can("finance_summary") && (
          <>
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} style={{ width: "auto" }} />
            <ExportButton kind="payments" label="Oy to'lovlari (Excel)" params={`month=${month}`} />
          </>
        )}
      </PageHead>
      <p className="muted" style={{ margin: 0 }}>
        To'lov o'quvchi kelgan kundan boshlab har 30 kunda olinadi; to'lov oynasi — tsiklning 3-darsidan 6-darsigacha.
        To'lovni yozish uchun O'quvchilar bo'limida o'quvchini oching yoki Jimiga ayting ("Ali 300 ming to'ladi").
      </p>
      {loading && !data ? <Loading /> : data && (
        <>
          <Card title={`Qarzdorlar (${data.qarzdorlar.length})`}><Table rows={data.qarzdorlar} debt /></Card>
          <Card title={`To'lov oynasi ochiq (${data.tolov_oynasi_ochiq.length})`}><Table rows={data.tolov_oynasi_ochiq} /></Card>
        </>
      )}
    </div>
  );
}

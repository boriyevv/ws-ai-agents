import { api, pct } from "../api";
import { Badge, Card, DataTable, Empty, Loading, PageHead, useApp, useLoad } from "../ui";

interface Row {
  teacher: string; group_name: string; davomat_30kun: number | null; faol_oquvchi: number; ketgan: number;
  imtihon_90: number; ball_90: number | null; ball_oldingi_90: number | null; maqsadga_yetdi: number; maqsadli_imtihon: number;
}

export default function Teachers() {
  const { me } = useApp();
  const { data, loading } = useLoad(() => api<{ guruhlar: Row[] }>("/api/teachers"));
  return (
    <div className="stack">
      <PageHead title={me.role === "teacher" ? "Mening natijalarim" : "O'qituvchilar"} />
      <p className="muted" style={{ margin: 0 }}>
        Davomat — so'nggi 30 kun; imtihonlar — so'nggi 90 kun, oldingi 90 kun bilan solishtiriladi. Bitta imtihon xulosa
        emas: tendensiyaga qarang. Chuqur tahlil uchun Jimidan so'rang.
      </p>
      <Card>
        {loading && !data ? <Loading /> : !data?.guruhlar.length ? <Empty>Guruhlarga o'qituvchi biriktirilmagan</Empty> : (
          <DataTable<Row> rows={data.guruhlar} cols={[
            { key: "teacher", label: "O'qituvchi", main: true, render: (r) => <span>{r.teacher} <span className="muted small">· {r.group_name}</span></span> },
            { key: "dav", label: "Davomat", render: (r) => <Badge tone={r.davomat_30kun === null ? "" : r.davomat_30kun < 0.75 ? "bad" : r.davomat_30kun < 0.85 ? "warn" : "ok"}>{pct(r.davomat_30kun)}</Badge> },
            { key: "faol", label: "O'quvchi", right: true, render: (r) => String(r.faol_oquvchi) },
            { key: "ketgan", label: "Ketgan", right: true, render: (r) => String(r.ketgan) },
            { key: "ball", label: "O'rtacha ball", right: true, render: (r) => {
              const trend = r.ball_90 !== null && r.ball_oldingi_90 !== null ? r.ball_90 - r.ball_oldingi_90 : null;
              return <span>{r.ball_90 ?? "—"}{trend !== null && <span className={trend < 0 ? "down" : "up"}> {trend < 0 ? "▼" : "▲"}{Math.abs(trend).toFixed(1)}</span>}</span>;
            } },
            { key: "goal", label: "Maqsadga yetdi", render: (r) => r.maqsadli_imtihon
              ? <Badge tone={r.maqsadga_yetdi / r.maqsadli_imtihon < 0.5 ? "bad" : r.maqsadga_yetdi / r.maqsadli_imtihon < 0.75 ? "warn" : "ok"}>{r.maqsadga_yetdi}/{r.maqsadli_imtihon}</Badge>
              : <span className="muted">—</span> },
          ]} />
        )}
      </Card>
    </div>
  );
}

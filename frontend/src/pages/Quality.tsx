import { api } from "../api";
import { Badge, Card, DataTable, Empty, Loading, PageHead, useLoad } from "../ui";

interface Q {
  oqituvchi: string; guruhlar: number; belgilangan_darslar: number; ortacha_kechikish_daqiqa: string | null;
  boshlanmagan_belgilanmagan: number; davomat_kiritilgan_darslar: number; davomat_kechikib: number;
  uy_vazifasi_berildi: number; uy_vazifasi_tekshirildi: number; ota_ona_bahosi: string | null; baholar_soni: number;
  imtihon_ortacha_90kun: number | null; imtihon_oldingi_90kun: number | null; ketgan_oquvchilar: number;
  davomat_30kun: number | null; dars_tahlillari: number;
}
interface S { oqituvchi: string | null; guruh: string | null; javoblar: number; ortacha: string | null; izohlar: string[] }
interface R { ism: string; guruh: string; sabablar: string[]; xavf: string }
interface Data { sifat: { oqituvchilar: Q[]; davr_kun: number }; sorovnoma: { yuborilgan: number; natijalar: S[] }; xavf?: { royxat: R[] } }

export default function Quality() {
  const { data, loading } = useLoad(() => api<Data>("/api/quality"));
  if (loading && !data) return <Loading />;
  if (!data) return <Empty />;
  return (
    <div className="stack">
      <PageHead title="Sifat nazorati" />
      <Card className="soft">
        <div className="small">
          Ko'rsatkichlar ma'lumotga asoslangan: o'qituvchi botda <b>/dars</b> orqali «Boshladim/Tugatdim» bosadi, davomat va uy
          vazifasini kiritadi, ota-onalar oyiga bir marta 1-5 baho beradi. Dars yozuvi faqat o'qituvchining o'z roziligi bilan
          tahlil qilinadi. Xulosa jazo uchun emas, yordam va rivojlanish uchun; qaror sizda.
        </div>
      </Card>
      <Card title={`O'qituvchilar (so'nggi ${data.sifat.davr_kun} kun)`}>
        <DataTable<Q> rows={data.sifat.oqituvchilar} empty="Guruhlarga o'qituvchi biriktirilmagan" cols={[
          { key: "oqituvchi", label: "O'qituvchi", main: true },
          { key: "vaqt", label: "Vaqtida boshlash", render: (r) => r.belgilangan_darslar
            ? <Badge tone={Number(r.ortacha_kechikish_daqiqa) > 10 ? "bad" : Number(r.ortacha_kechikish_daqiqa) > 5 ? "warn" : "ok"}>≈ {r.ortacha_kechikish_daqiqa ?? 0} daq kech</Badge>
            : <span className="muted">tugma bosilmagan</span> },
          { key: "dav", label: "Davomat", render: (r) => r.davomat_30kun === null ? "—" : `${Math.round(r.davomat_30kun * 100)}%` },
          { key: "jurnal", label: "Jurnal kechikkan", render: (r) => `${r.davomat_kechikib}/${r.davomat_kiritilgan_darslar}` },
          { key: "uy", label: "Uy vazifasi", render: (r) => `${r.uy_vazifasi_tekshirildi}/${r.uy_vazifasi_berildi} tekshirildi` },
          { key: "imt", label: "Imtihon (90 kun)", render: (r) => r.imtihon_ortacha_90kun === null ? "—" : (
            <span>{r.imtihon_ortacha_90kun}{r.imtihon_oldingi_90kun !== null && (
              <span className={r.imtihon_ortacha_90kun >= r.imtihon_oldingi_90kun ? "up" : "down"}> {r.imtihon_ortacha_90kun >= r.imtihon_oldingi_90kun ? "▲" : "▼"}</span>)}</span>) },
          { key: "baho", label: "Ota-ona bahosi", render: (r) => r.ota_ona_bahosi ? <Badge tone={Number(r.ota_ona_bahosi) < 4 ? "warn" : "ok"}>{r.ota_ona_bahosi} ⭐ ({r.baholar_soni})</Badge> : "—" },
          { key: "ket", label: "Ketgan", right: true, render: (r) => String(r.ketgan_oquvchilar) },
        ]} />
      </Card>
      <div className="grid two">
        <Card title={`Ota-onalar so'rovnomasi (yuborilgan: ${data.sorovnoma.yuborilgan})`}>
          {!data.sorovnoma.natijalar.length ? <Empty>Javoblar yo'q. Jimiga ayting: «Jimi, ota-onalarga oylik so'rovnoma yubor».</Empty> : (
            <div className="list">
              {data.sorovnoma.natijalar.map((s, i) => (
                <div className="list-item" key={i} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div className="row"><b className="spacer">{s.oqituvchi ?? "—"} · {s.guruh ?? "—"}</b>
                    <Badge tone={Number(s.ortacha) < 4 ? "warn" : "ok"}>{s.ortacha} ⭐ ({s.javoblar})</Badge></div>
                  {s.izohlar.map((c, j) => <div key={j} className="muted small">«{c}»</div>)}
                </div>
              ))}
            </div>
          )}
        </Card>
        {data.xavf && (
          <Card title={`Ketib qolish xavfi (${data.xavf.royxat.length})`}>
            {!data.xavf.royxat.length ? <Empty>Hozircha xavfli holat yo'q</Empty> : (
              <div className="list">
                {data.xavf.royxat.map((r, i) => (
                  <div className="list-item" key={i} style={{ flexDirection: "column", alignItems: "stretch" }}>
                    <div className="row"><b className="spacer">{r.ism}</b><Badge tone={r.xavf === "yuqori" ? "bad" : "warn"}>{r.xavf}</Badge></div>
                    <div className="muted small">{r.guruh}: {r.sabablar.join("; ")}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

import { api, fmtDate, money, moneyShort, num } from "../api";
import { Badge, Card, Empty, Kpi, Loading, PageHead, useAction, useApp, useLoad } from "../ui";

interface Dashboard {
  sana: string;
  faol_oquvchilar: number;
  muzlatilgan: number;
  bugungi_darslar: {
    id: string; name: string; start_time: string; end_time: string; branch: string; room: string | null;
    teacher: string | null; students: number; marked: boolean;
  }[];
  qarzdorlar_soni?: number;
  tolov_oynasi_soni?: number;
  qarz_summa?: number;
  qarzdorlar?: { id: string; ism: string; guruh: string; summa: number | null }[];
  kelmayotganlar?: { ism: string; guruh: string }[];
  lidlar_7_kun?: number;
  javobsiz_lidlar?: number;
  tushum_oy?: number;
  foyda_oy?: number;
  tasdiqlar?: { id: string; kim: string; nima: string; created_at: string }[];
  mening_vazifalarim: { id: string; text: string; due_at: string | null; status: string; kimdan: string | null }[];
  bergan_ochiq_vazifalar?: number;
  rejalashtirilgan_postlar?: number;
}

export default function Home() {
  const { me } = useApp();
  const { data, loading, reload } = useLoad(() => api<Dashboard>("/api/dashboard"));
  const { busy, run } = useAction();

  if (loading && !data) return <Loading />;
  if (!data) return <Empty>Ma'lumot yuklanmadi.</Empty>;

  const decide = (id: string, approve: boolean) =>
    run(() => api(`/api/approvals/${id}`, { body: { approve } }), approve ? "Tasdiqlandi" : "Rad etildi").then(reload);

  const unmarked = data.bugungi_darslar.filter((g) => !g.marked).length;

  return (
    <div className="stack">
      <PageHead title={`Salom, ${me.name.split(" ")[0]}!`}>
        <span className="muted">{fmtDate(data.sana)}</span>
      </PageHead>

      <div className="grid kpis">
        <Kpi label="Faol o'quvchilar" value={num(data.faol_oquvchilar)} hint={data.muzlatilgan ? `${data.muzlatilgan} ta muzlatilgan` : undefined} />
        <Kpi label="Bugungi darslar" value={data.bugungi_darslar.length} hint={unmarked ? `${unmarked} tasida davomat yo'q` : "Davomat to'liq"} />
        {data.qarzdorlar_soni !== undefined && (
          <Kpi label="Qarzdorlar" value={data.qarzdorlar_soni} tone={data.qarzdorlar_soni ? "alert" : "good"}
            hint={data.qarz_summa ? `≈ ${money(data.qarz_summa)}` : undefined} />
        )}
        {data.tolov_oynasi_soni !== undefined && (
          <Kpi label="To'lov oynasi ochiq" value={data.tolov_oynasi_soni} hint="3–6 dars oralig'ida" />
        )}
        {data.lidlar_7_kun !== undefined && (
          <Kpi label="Yangi lidlar (7 kun)" value={data.lidlar_7_kun}
            tone={data.javobsiz_lidlar ? "alert" : undefined}
            hint={data.javobsiz_lidlar ? `${data.javobsiz_lidlar} tasi javobsiz` : undefined} />
        )}
        {data.bergan_ochiq_vazifalar !== undefined && (
          <Kpi label="Berilgan vazifalar" value={data.bergan_ochiq_vazifalar} hint="bajarilmagan" />
        )}
        {data.rejalashtirilgan_postlar !== undefined && (
          <Kpi label="Rejadagi postlar" value={data.rejalashtirilgan_postlar} hint="avtomatik chiqadi" />
        )}
        {data.tushum_oy !== undefined && (
          <Kpi label="Shu oy tushum" value={moneyShort(data.tushum_oy)} hint={`Foyda ≈ ${money(data.foyda_oy)}`} />
        )}
      </div>

      {data.mening_vazifalarim.length > 0 && (
        <Card title={`Mening vazifalarim (${data.mening_vazifalarim.length})`} action={<a href="#/tasks" className="small">Hammasi →</a>}>
          <div className="list">
            {data.mening_vazifalarim.map((t) => (
              <div className="list-item" key={t.id}>
                <div><div className="pre">{t.text}</div><div className="muted small">{t.kimdan}{t.due_at ? ` · muddat ${fmtDate(t.due_at)} ${new Date(t.due_at).toTimeString().slice(0, 5)}` : ""}</div></div>
                <button className="primary" disabled={busy} onClick={() => run(() => api(`/api/tasks/${t.id}`, { body: { status: "done" } }), "Bajarildi").then(reload)}>Bajarildi</button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.tasdiqlar && data.tasdiqlar.length > 0 && (
        <Card title={`Tasdiq kutayotgan so'rovlar (${data.tasdiqlar.length})`}>
          <div className="list">
            {data.tasdiqlar.map((a) => (
              <div className="list-item" key={a.id} style={{ flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 220px" }}>
                  <div>{a.nima}</div>
                  <div className="muted small">{a.kim}</div>
                </div>
                <div className="row" style={{ flex: "0 1 auto", flexWrap: "nowrap" }}>
                  <button className="primary" disabled={busy} onClick={() => decide(a.id, true)}>Tasdiqlash</button>
                  <button className="danger" disabled={busy} onClick={() => decide(a.id, false)}>Rad etish</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid two">
        <Card title="Bugungi darslar">
          {data.bugungi_darslar.length === 0 ? <Empty>Bugun dars yo'q</Empty> : (
            <div className="list">
              {data.bugungi_darslar.map((g) => (
                <a className="list-item plain" key={g.id} href={`#/groups/${g.id}`}>
                  <div>
                    <div><b className="num">{g.start_time.slice(0, 5)}</b> &nbsp;{g.name}</div>
                    <div className="muted small">{[g.branch, g.room, g.teacher, `${g.students} o'quvchi`].filter(Boolean).join(" · ")}</div>
                  </div>
                  {g.marked ? <Badge tone="ok">Belgilangan</Badge> : <Badge tone="warn">Davomat kerak</Badge>}
                </a>
              ))}
            </div>
          )}
        </Card>

        {data.qarzdorlar && (
          <Card title="Qarzdorlar" action={<a href="#/payments" className="small">Hammasi →</a>}>
            {data.qarzdorlar.length === 0 ? <Empty>Qarzdor yo'q 🎉</Empty> : (
              <div className="list">
                {data.qarzdorlar.map((d) => (
                  <div className="list-item" key={d.id + d.guruh}>
                    <div>{d.ism}<div className="muted small">{d.guruh}</div></div>
                    <span className="num">{money(d.summa)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {data.kelmayotganlar && (
          <Card title="3 darsdan beri kelmayotganlar">
            {data.kelmayotganlar.length === 0 ? <Empty>Bunday o'quvchi yo'q</Empty> : (
              <div className="list">
                {data.kelmayotganlar.map((s, i) => (
                  <div className="list-item" key={i}>
                    <span>{s.ism}</span>
                    <span className="muted small">{s.guruh}</span>
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

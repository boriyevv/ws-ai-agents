import { useState } from "react";
import { api } from "../api";
import { Badge, Card, Loading, PageHead, useAction, useLoad } from "../ui";

interface Data {
  sozlamalar: { kalit: string; nima: string; qiymat: string | null }[];
  ulanishlar: { nom: string; ulangan: boolean; kalit: string }[];
  tahrir_qila_oladi: boolean;
  rahbar: boolean;
}
const OWNER_ONLY = ["review_url", "referral_bonus_percent", "meta_usd_rate", "auto_monthly_survey"];

export default function Settings() {
  const { data, loading, reload } = useLoad(() => api<Data>("/api/settings"));
  const { busy, run } = useAction();
  const [edit, setEdit] = useState<Record<string, string>>({});
  if (loading && !data) return <Loading />;
  if (!data) return null;
  const save = (key: string) => {
    if (!confirm("Sozlama saqlansinmi?")) return;
    run(() => api("/api/settings", { body: { key, value: edit[key] } }), "Saqlandi").then(() => { setEdit({ ...edit, [key]: undefined as unknown as string }); reload(); });
  };
  return (
    <div className="stack">
      <PageHead title="Sozlamalar" />
      <Card title="Ulanishlar">
        <p className="muted small" style={{ marginTop: 0 }}>Kalitlar faqat serverdagi <code>.env</code> faylda turadi (bu yerda ko'rsatilmaydi). Qanday ulash — README.</p>
        <div className="list">
          {data.ulanishlar.map((u) => (
            <div className="list-item" key={u.nom}>
              <div>{u.nom}<div className="muted small">{u.kalit}</div></div>
              {u.ulangan ? <Badge tone="ok">Ulangan</Badge> : <Badge tone="warn">Ulanmagan</Badge>}
            </div>
          ))}
        </div>
      </Card>
      <Card title="Markaz sozlamalari">
        <div className="stack" style={{ gap: 18 }}>
          {data.sozlamalar.map((s) => {
            const can = data.tahrir_qila_oladi && (data.rahbar || !OWNER_ONLY.includes(s.kalit));
            const v = edit[s.kalit] ?? s.qiymat ?? "";
            return (
              <div key={s.kalit}>
                <label className="field">{s.nima}
                  {s.kalit === "brand_voice"
                    ? <textarea rows={4} value={v} disabled={!can} onChange={(e) => setEdit({ ...edit, [s.kalit]: e.target.value })} />
                    : <input value={v} disabled={!can} onChange={(e) => setEdit({ ...edit, [s.kalit]: e.target.value })} />}
                </label>
                {can && edit[s.kalit] !== undefined && edit[s.kalit] !== s.qiymat && (
                  <div className="row" style={{ justifyContent: "flex-end", marginTop: 6 }}>
                    <button className="primary" disabled={busy} onClick={() => save(s.kalit)}>Saqlash</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <p className="muted small">Markaz ohangini Jimiga gapirib ham o'rgatish mumkin: «Jimi, postlarni samimiyroq, lekin "siz" deb yozinglar».</p>
      </Card>
    </div>
  );
}

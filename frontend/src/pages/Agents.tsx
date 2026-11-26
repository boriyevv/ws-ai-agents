import { api } from "../api";
import { Badge, Card, Empty, Loading, PageHead, useAction, useApp, useLoad } from "../ui";

interface Agent { nom: string; lavozim: string; vazifa: string; vositalar: string[] }
interface Data { agentlar: Agent[]; katalog: Agent[]; ornata_oladi: boolean }

const ICON: Record<string, string> = {
  jimi: "🧠", hr: "🧑‍💼", finance: "💰", office_manager: "🏫", ads: "📣", content_strategist: "🗓", copywriter: "✍️",
  video: "🎬", designer: "🎨", publisher: "🚀", community: "💬", competitors: "🔍", reports: "📊", quality: "🎯",
  retention: "🤝", reviews: "⭐", referral: "🎁", recruiter: "🧲", scheduler: "🗂", sotuv: "📞", tadbirlar: "🎉", ota_onalar: "👪",
};
const GROUPS: [string, string[]][] = [
  ["Rahbariyat", ["jimi", "hr", "finance", "reports"]],
  ["Media va marketing", ["content_strategist", "copywriter", "video", "designer", "publisher", "community", "ads", "competitors"]],
  ["O'quv jarayoni", ["office_manager", "quality", "retention", "reviews", "referral", "recruiter", "scheduler"]],
];

function AgentCard({ a, action, footer }: { a: Agent; action?: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div className="card agent-card">
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <span style={{ fontSize: 26 }} aria-hidden>{ICON[a.nom] ?? "🤖"}</span>
        <div className="spacer" style={{ minWidth: 0 }}><b>{a.lavozim}</b><div className="muted small">{a.nom}</div></div>
        {action}
      </div>
      <div className="small">{a.vazifa}</div>
      <div className="tools">{(a.vositalar[0] === "all" ? ["barcha vositalar"] : a.vositalar).map((t) => <span key={t}>{t}</span>)}</div>
      {footer && <div className="row" style={{ justifyContent: "flex-end", marginTop: "auto" }}>{footer}</div>}
    </div>
  );
}

export default function Agents() {
  const { me } = useApp();
  const { data, loading, reload } = useLoad(() => api<Data>("/api/agents"));
  const { busy, run } = useAction();
  if (loading && !data) return <Loading />;
  if (!data) return <Empty />;
  const byName = Object.fromEntries(data.agentlar.map((a) => [a.nom, a]));
  const grouped = new Set(GROUPS.flatMap(([, n]) => n));
  const others = data.agentlar.filter((a) => !grouped.has(a.nom));

  const install = (a: Agent) => {
    if (!confirm(`«${a.lavozim}» agentini jamoaga qo'shamizmi?`)) return;
    run(() => api<{ status?: string }>("/api/agents/install", { body: { name: a.nom } })).then((r) => {
      if (r?.status === "sent_to_owner") alert("So'rov rahbarga tasdiq uchun yuborildi.");
      reload();
    });
  };
  const deactivate = (a: Agent) => {
    if (!confirm(`«${a.lavozim}» agentini to'xtatamizmi? (keyin katalogdan qayta qo'shish mumkin)`)) return;
    run(() => api(`/api/agents/${a.nom}/deactivate`, { method: "POST" }), "To'xtatildi").then(reload);
  };
  const off = (a: Agent) => me.role === "owner" && a.nom !== "jimi"
    ? <button className="link small" disabled={busy} onClick={() => deactivate(a)}>To'xtatish</button> : undefined;

  return (
    <div className="stack">
      <PageHead title="AI jamoa"><Badge tone="info">{data.agentlar.length} ta agent ishlamoqda</Badge></PageHead>
      <p className="muted" style={{ margin: 0 }}>
        Hammasiga Jimi orqali murojaat qilasiz: u topshiriqni kerakli mutaxassisga beradi. Yangi yo'nalish kerak bo'lsa
        HR agenti sizdan so'rab katalogdan agent olib keladi yoki yangisini yaratadi — siz tasdiqlaguningizcha hech narsa
        ishga tushmaydi. Agentlar faqat tizimdagi vositalardan foydalanadi.
      </p>
      {GROUPS.map(([title, names]) => {
        const list = names.map((n) => byName[n]).filter(Boolean);
        return list.length ? (
          <div key={title} className="stack" style={{ gap: 10 }}>
            <h2>{title}</h2>
            <div className="grid cards">{list.map((a) => <AgentCard key={a.nom} a={a} footer={off(a)} />)}</div>
          </div>
        ) : null;
      })}
      {others.length > 0 && (
        <div className="stack" style={{ gap: 10 }}>
          <h2>Qo'shimcha (HR qo'shgan)</h2>
          <div className="grid cards">{others.map((a) => <AgentCard key={a.nom} a={a} footer={off(a)} />)}</div>
        </div>
      )}
      <Card title="Katalog: tayyor agentlar">
        {!data.katalog.length ? <Empty>Katalog bo'sh — hammasi o'rnatilgan.</Empty> : (
          <div className="grid cards">
            {data.katalog.map((a) => (
              <AgentCard key={a.nom} a={a} action={data.ornata_oladi ? (
                <button className="primary" disabled={busy} onClick={() => install(a)}>Qo'shish</button>) : undefined} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

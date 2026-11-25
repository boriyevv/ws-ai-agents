import { useEffect, useState } from "react";
import { api, fmtDate, todayISO } from "../api";
import { Badge, Card, DataTable, Empty, Field, Loading, Modal, PageHead, Tabs, useAction, useApp, useLoad } from "../ui";

type Tab = "posts" | "plan" | "design" | "comments";

export default function Content() {
  const { can } = useApp();
  const [tab, setTab] = useState<Tab>(can("list_posts") ? "posts" : "design");
  const [draftFile, setDraftFile] = useState<File | null>(null);
  const [composer, setComposer] = useState(false);
  const openComposer = (f: File | null = null) => { setDraftFile(f); setComposer(true); };
  return (
    <div className="stack">
      <PageHead title="Kontent">
        {can("publish_post") && <button className="primary" onClick={() => openComposer()}>+ Yangi post</button>}
      </PageHead>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { key: "posts", label: "Postlar", show: can("list_posts") },
        { key: "plan", label: "Oylik reja", show: can("list_content_plan") },
        { key: "design", label: "Dizayn", show: can("make_design") },
        { key: "comments", label: "Izohlar", show: can("list_comments") },
      ]} />
      {tab === "posts" && <Posts key={String(composer)} />}
      {tab === "plan" && <Plan />}
      {tab === "design" && <Design onUse={(f) => openComposer(f)} />}
      {tab === "comments" && <Comments />}
      <Modal title="Yangi post" open={composer} onClose={() => setComposer(false)}>
        <Composer initialFile={draftFile} onDone={() => { setComposer(false); setTab("posts"); }} />
      </Modal>
    </div>
  );
}

// ---------- postlar ----------
interface Post {
  id: string; body: string | null; media_kind: string; media_url: string | null; targets: string[]; status: string;
  scheduled_at: string; published_at: string | null; results: Record<string, { ok: boolean; xato?: string }>; kim: string | null;
}
const STATUS: Record<string, [string, string]> = {
  scheduled: ["Rejalashtirilgan", "info"], publishing: ["Chiqmoqda", "warn"], published: ["Chiqdi", "ok"],
  partial: ["Qisman", "warn"], failed: ["Xato", "bad"], cancelled: ["Bekor", ""],
};
const fmtDT = (s: string | null) => (s ? `${fmtDate(s)} ${new Date(s).toTimeString().slice(0, 5)}` : "—");

function Posts() {
  const { data, loading, reload } = useLoad(() => api<{ postlar: Post[]; sozlamalar: Record<string, boolean> }>("/api/content"));
  const { run } = useAction();
  if (loading && !data) return <Loading />;
  const st = data?.sozlamalar;
  return (
    <div className="stack">
      {st && (!st.telegram || !st.instagram || !st.storage) && (
        <Card className="soft">
          <div className="small">
            Ulanish holati: Telegram kanal {st.telegram ? "✅" : "❌"} · Instagram {st.instagram ? "✅" : "❌"} · Fayl saqlash {st.storage ? "✅" : "❌"}.
            {" "}Sozlash: <a href="#/settings">Sozlamalar</a> va README.
          </div>
        </Card>
      )}
      <Card>
        <DataTable<Post> rows={data?.postlar ?? []} empty="Hali post yo'q" rowKey={(p) => p.id} cols={[
          { key: "body", label: "Post", main: true, render: (p) => <span>{p.media_kind === "video" ? "🎬 " : p.media_kind === "photo" ? "🖼 " : ""}{(p.body ?? "").slice(0, 90)}</span> },
          { key: "targets", label: "Qayerga", render: (p) => p.targets.join(", ") },
          { key: "time", label: "Vaqt", render: (p) => fmtDT(p.published_at ?? p.scheduled_at) },
          { key: "status", label: "Holat", render: (p) => {
            const [t, tone] = STATUS[p.status] ?? [p.status, ""];
            const errs = Object.entries(p.results || {}).filter(([, r]) => !r.ok).map(([k, r]) => `${k}: ${r.xato}`).join("; ");
            return <span title={errs}><Badge tone={tone}>{t}</Badge>{errs && <div className="down small">{errs.slice(0, 120)}</div>}</span>;
          } },
          { key: "act", label: "", right: true, render: (p) => p.status === "scheduled" ? (
            <button className="danger" onClick={() => run(() => api(`/api/content/${p.id}/cancel`, { method: "POST" }), "Bekor qilindi").then(reload)}>Bekor</button>
          ) : null },
        ]} />
      </Card>
    </div>
  );
}

function Composer({ initialFile, onDone }: { initialFile: File | null; onDone: () => void }) {
  const { busy, run } = useAction();
  const [text, setText] = useState("");
  const [topic, setTopic] = useState("");
  const [targets, setTargets] = useState<string[]>(["telegram"]);
  const [file, setFile] = useState<File | null>(initialFile);
  const [when, setWhen] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return setPreview(null);
    const u = URL.createObjectURL(file);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  const isVideo = file?.type.startsWith("video/");

  const draft = () => run(() => api<{ matn: string }>("/api/content/draft", { body: { topic, targets } }))
    .then((r) => r && setText(r.matn));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirm(when ? `Post ${when.replace("T", " ")} da chiqadi. Tasdiqlaysizmi?` : `Post hozir ${targets.join(", ")} ga chiqadi. Tasdiqlaysizmi?`)) return;
    const fd = new FormData();
    fd.append("text", text);
    fd.append("targets", targets.join(","));
    if (when) fd.append("schedule_at", when.replace("T", " "));
    if (file) fd.append("media", file);
    run(() => api<{ holat?: string }>("/api/content", { body: fd }), when ? "Rejalashtirildi" : "Yuborildi").then((r) => r && onDone());
  };
  const toggle = (t: string) => setTargets(targets.includes(t) ? targets.filter((x) => x !== t) : [...targets, t]);

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Mavzu (Jimi matnni yozib beradi)" full>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Masalan: 30-noyabr ochiq eshiklar kuni, bepul sinov darsi" />
          <button type="button" disabled={busy || !topic.trim()} onClick={draft}>✨ Yozib ber</button>
        </div>
      </Field>
      <Field label="Post matni" full><textarea required rows={7} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      <Field label="Rasm yoki video (50 MB gacha)" full>
        <input type="file" accept="image/*,video/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      {preview && (isVideo ? <video src={preview} controls className="design-preview full" /> : <img src={preview} alt="" className="design-preview full" />)}
      <Field label="Qayerga" full>
        <div className="days">
          {[["telegram", "Telegram kanal"], ["instagram", "Instagram"], ["youtube", "YouTube Shorts"], ["tiktok", "TikTok"]].map(([k, l]) => (
            <label key={k}><input type="checkbox" checked={targets.includes(k)} onChange={() => toggle(k)} /> {l}</label>
          ))}
        </div>
      </Field>
      <Field label="Chiqish vaqti (bo'sh = hozir)"><input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
      <div className="form-actions"><button className="primary" disabled={busy || !targets.length || !text.trim()}>{when ? "Rejalashtirish" : "Chiqarish"}</button></div>
      <p className="muted small full" style={{ margin: 0 }}>
        Telegram postiga avtomatik «yozilish» havolasi qo'shiladi: qaysi post murojaat keltirgani Lidlar va Reja bo'limida ko'rinadi.
        YouTube va TikTok faqat video, n8n/Make orqali.
      </p>
    </form>
  );
}

// ---------- oylik reja ----------
interface PlanItem { id: string; plan_date: string; category: string; topic: string; channels: string[]; status: string }
const CAT: Record<string, string> = { natija: "O'quvchi natijasi", oqituvchi: "O'qituvchi", maslahat: "Foydali maslahat", aksiya: "Aksiya", tadbir: "Tadbir", boshqa: "Boshqa" };
const PSTATUS: Record<string, string> = { rejada: "info", tayyor: "warn", chiqdi: "ok", bekor: "" };

function Plan() {
  const [month, setMonth] = useState(todayISO().slice(0, 7));
  const { data, loading, reload } = useLoad(() => api<{ reja: PlanItem[] }>(`/api/plan?month=${month}`), [month]);
  const { busy, run } = useAction();
  const [f, setF] = useState({ date: todayISO(), category: "maslahat", topic: "" });
  const add = (e: React.FormEvent) => {
    e.preventDefault();
    run(() => api("/api/plan", { body: { items: [{ ...f, channels: ["telegram", "instagram"] }] } }), "Qo'shildi")
      .then(() => { setF({ ...f, topic: "" }); reload(); });
  };
  const counts = (data?.reja ?? []).reduce<Record<string, number>>((a, r) => ({ ...a, [r.category]: (a[r.category] ?? 0) + 1 }), {});
  return (
    <div className="stack">
      <Card title="Reja" action={<input type="month" value={month} onChange={(e) => setMonth(e.target.value)} style={{ width: "auto" }} />}>
        <p className="muted small" style={{ marginTop: 0 }}>
          Jimiga ayting: «Jimi, keyingi oy uchun kontent reja tuz» — kontent strateg o'tgan oy qaysi postlar murojaat keltirganini
          tahlil qilib rejani yozadi. Har oyning 25-sanasida bu avtomatik ham bajariladi.
        </p>
        <div className="row" style={{ marginBottom: 10 }}>
          {Object.entries(counts).map(([k, n]) => <Badge key={k} tone="info">{CAT[k] ?? k}: {n}</Badge>)}
        </div>
        {loading && !data ? <Loading /> : (
          <DataTable<PlanItem> rows={data?.reja ?? []} empty="Bu oy uchun reja yo'q" rowKey={(r) => r.id} cols={[
            { key: "plan_date", label: "Sana", render: (r) => fmtDate(r.plan_date) },
            { key: "topic", label: "Mavzu", main: true },
            { key: "category", label: "Toifa", render: (r) => CAT[r.category] ?? r.category },
            { key: "status", label: "Holat", render: (r) => (
              <select value={r.status} style={{ width: "auto", minHeight: 32 }}
                onChange={(e) => run(() => api(`/api/plan/${r.id}`, { body: { status: e.target.value } })).then(reload)}>
                {Object.keys(PSTATUS).map((s) => <option key={s}>{s}</option>)}
              </select>) },
          ]} />
        )}
      </Card>
      <Card title="Rejaga qo'shish">
        <form className="form" onSubmit={add}>
          <Field label="Sana"><input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Toifa"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
            {Object.entries(CAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Mavzu" full><input required value={f.topic} onChange={(e) => setF({ ...f, topic: e.target.value })} /></Field>
          <div className="form-actions"><button className="primary" disabled={busy}>Qo'shish</button></div>
        </form>
      </Card>
    </div>
  );
}

// ---------- dizayn ----------
function Design({ onUse }: { onUse: (f: File) => void }) {
  const { can } = useApp();
  const { data: tpl } = useLoad(() => api<{ shablonlar: { nom: string; tavsif: string }[]; formatlar: string[] }>("/api/design/templates"));
  const { busy, run } = useAction();
  const [f, setF] = useState({ template: "natija", format: "post", title: "", score: "", subtitle: "", details: "", badge: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [img, setImg] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  const make = (e: React.FormEvent) => {
    e.preventDefault();
    const fd = new FormData();
    Object.entries(f).forEach(([k, v]) => fd.append(k, v));
    if (photo) fd.append("photo", photo);
    run(() => api<{ rasm: string }>("/api/design", { body: fd })).then((r) => r && setImg(r.rasm));
  };
  const toFile = () => {
    const bin = atob(img!);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new File([arr], `${f.template}.png`, { type: "image/png" });
  };
  const desc = tpl?.shablonlar.find((t) => t.nom === f.template)?.tavsif;

  return (
    <div className="grid two">
      <Card title="Kartochka">
        <form className="form" onSubmit={make}>
          <Field label="Shablon"><select value={f.template} onChange={set("template")}>
            {tpl?.shablonlar.map((t) => <option key={t.nom} value={t.nom}>{t.nom}</option>)}</select></Field>
          <Field label="Format"><select value={f.format} onChange={set("format")}>
            <option value="post">Post 1080×1080</option><option value="story">Story 1080×1920</option><option value="afisha">Afisha 1080×1350</option></select></Field>
          {desc && <p className="muted small full" style={{ margin: 0 }}>{desc}</p>}
          <Field label="Sarlavha (title)" full><input required value={f.title} onChange={set("title")} /></Field>
          <Field label="Katta raqam (score)"><input value={f.score} onChange={set("score")} placeholder="IELTS 7.5 / -30%" /></Field>
          <Field label="Yorliq (badge)"><input value={f.badge} onChange={set("badge")} /></Field>
          <Field label="Kichik sarlavha" full><input value={f.subtitle} onChange={set("subtitle")} /></Field>
          <Field label="Qo'shimcha matn (har qator alohida)" full><textarea value={f.details} onChange={set("details")} /></Field>
          {f.template === "natija" && <Field label="O'quvchi surati (ixtiyoriy)" full><input type="file" accept="image/*" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} /></Field>}
          <div className="form-actions"><button className="primary" disabled={busy}>Tayyorlash</button></div>
        </form>
      </Card>
      <Card title="Natija">
        {!img ? <Empty>Chap tomonda ma'lumotni kiriting va «Tayyorlash»ni bosing.</Empty> : (
          <div className="stack">
            <img className="design-preview" src={`data:image/png;base64,${img}`} alt="Dizayn" />
            <div className="row">
              <a className="btn" download={`${f.template}.png`} href={`data:image/png;base64,${img}`}>⬇ Yuklab olish</a>
              {can("publish_post") && <button className="primary" onClick={() => onUse(toFile())}>Post qilish →</button>}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------- izohlar ----------
interface Comment { id: string; username: string | null; text: string; category: string; suggested_reply: string | null; status: string; created_at: string }
const CC: Record<string, [string, string]> = { savol: ["Savol", "info"], yozilish: ["Yozilmoqchi", "ok"], ijobiy: ["Ijobiy", "ok"], salbiy: ["Salbiy", "bad"], spam: ["Spam", ""] };

function Comments() {
  const [status, setStatus] = useState("yangi");
  const { data, loading, reload } = useLoad(() => api<{ izohlar: Comment[] }>(`/api/comments?status=${status}`), [status]);
  const { busy, run } = useAction();
  const [edit, setEdit] = useState<Record<string, string>>({});
  return (
    <Card title="Instagram va Telegram izohlari" action={
      <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
        <option value="yangi">Yangi</option><option value="javob_berildi">Javob berilgan</option><option value="etiborsiz">E'tiborsiz</option>
      </select>}>
      <p className="muted small" style={{ marginTop: 0 }}>Izohlar har 15 daqiqada tekshiriladi, AI turini aniqlab javob tayyorlaydi. Salbiylari rahbarga darhol boradi.</p>
      {loading && !data ? <Loading /> : !data?.izohlar.length ? <Empty>Izoh yo'q</Empty> : (
        <div className="list">
          {data.izohlar.map((c) => {
            const [t, tone] = CC[c.category] ?? [c.category, ""];
            return (
              <div key={c.id} className="list-item" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className="row"><b>@{c.username ?? "?"}</b><Badge tone={tone}>{t}</Badge>
                  <span className="muted small">{c.id.startsWith("tg:") ? "Telegram" : "Instagram"} · {fmtDT(c.created_at)}</span></div>
                <div className="pre">{c.text}</div>
                {status === "yangi" && c.category !== "spam" && (
                  <>
                    <textarea value={edit[c.id] ?? c.suggested_reply ?? ""} onChange={(e) => setEdit({ ...edit, [c.id]: e.target.value })} />
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button disabled={busy} onClick={() => run(() => api(`/api/comments/${encodeURIComponent(c.id)}`, { body: { action: "skip" } })).then(reload)}>E'tiborsiz</button>
                      <button className="primary" disabled={busy || !(edit[c.id] ?? c.suggested_reply)}
                        onClick={() => run(() => api(`/api/comments/${encodeURIComponent(c.id)}`, { body: { text: edit[c.id] ?? c.suggested_reply } }), "Javob yuborildi").then(reload)}>Javob yuborish</button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

import { useEffect, useState } from "react";
import type { PageProps } from "../App";
import { api, DAYS, todayISO, type Group } from "../api";
import { Badge, Card, Empty, ExportButton, Field, Loading, Modal, PageHead, useAction, useApp, useLoad } from "../ui";

export default function Groups({ param }: PageProps) {
  return param ? <Attendance groupId={param} /> : <GroupList />;
}

function GroupList() {
  const { can } = useApp();
  const { data, loading, reload } = useLoad(() => api<{ guruhlar: Group[] }>("/api/groups"));
  const [open, setOpen] = useState(false);
  return (
    <div className="stack">
      <PageHead title="Guruhlar">
        {can("create_group") && <button className="primary" onClick={() => setOpen(true)}>+ Yangi guruh</button>}
      </PageHead>
      {loading && !data ? <Loading /> : !data?.guruhlar.length ? <Empty>Hali guruh yo'q</Empty> : (
        <div className="grid cards">
          {data.guruhlar.map((g) => (
            <a key={g.id} className="card group-card plain" href={`#/groups/${g.id}`}>
              <div className="row"><h3 className="spacer">{g.nom}</h3><Badge tone="info">{g.oquvchilar} o'quvchi</Badge></div>
              <div className="meta">{g.jadval}</div>
              <div className="meta">{[g.filial, g.xona, g.oqituvchi].filter(Boolean).join(" · ")}</div>
            </a>
          ))}
        </div>
      )}
      <Modal title="Yangi guruh ochish" open={open} onClose={() => setOpen(false)}>
        <NewGroup onDone={() => { setOpen(false); reload(); }} />
      </Modal>
    </div>
  );
}

function NewGroup({ onDone }: { onDone: () => void }) {
  const { me } = useApp();
  const { busy, run } = useAction();
  const [f, setF] = useState({ name: "", subject: "", branch: me.branches[0]?.name ?? "", teacher: "", room: "",
    start_time: "14:00", end_time: "16:00" });
  const [days, setDays] = useState<number[]>([1, 3, 5]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(() => api("/api/groups", { body: { ...f, days } }), "Guruh ochildi").then((r) => r && onDone());
  };
  return (
    <form className="form" onSubmit={submit}>
      <Field label="Guruh nomi"><input required value={f.name} onChange={set("name")} placeholder="Ingliz 3" /></Field>
      <Field label="Fan"><input required value={f.subject} onChange={set("subject")} placeholder="Ingliz tili" /></Field>
      <Field label="Filial">
        <select value={f.branch} onChange={set("branch")}>
          {me.branches.map((b) => <option key={b.id} value={b.name}>{b.name}</option>)}
        </select>
      </Field>
      <Field label="O'qituvchi"><input value={f.teacher} onChange={set("teacher")} /></Field>
      <Field label="Xona"><input value={f.room} onChange={set("room")} placeholder="1-xona" /></Field>
      <Field label="Boshlanishi"><input type="time" value={f.start_time} onChange={set("start_time")} /></Field>
      <Field label="Tugashi"><input type="time" value={f.end_time} onChange={set("end_time")} /></Field>
      <Field label="Dars kunlari" full>
        <div className="days">
          {DAYS.map((d, i) => (
            <label key={d}>
              <input type="checkbox" checked={days.includes(i + 1)}
                onChange={(e) => setDays(e.target.checked ? [...days, i + 1] : days.filter((x) => x !== i + 1))} />
              {d}
            </label>
          ))}
        </div>
      </Field>
      <div className="form-actions"><button className="primary" disabled={busy}>Guruh ochish</button></div>
    </form>
  );
}

interface AttRow { id: string; ism: string; holat: "present" | "absent" | "belgilanmagan" }
interface AttData { guruh: string; sana: string; royxat: AttRow[]; dars_kuni: boolean }
interface MarkResult {
  kelmadi: number; keldi: number;
  kelmaganlar: { id: string; full_name: string; ota_ona_ulangan: boolean; telefon: string | null }[];
}

function Attendance({ groupId }: { groupId: string }) {
  const { can } = useApp();
  const [date, setDate] = useState(todayISO());
  const { data, loading } = useLoad(() => api<AttData>(`/api/groups/${groupId}/attendance?date=${date}`), [date]);
  const [absent, setAbsent] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<MarkResult | null>(null);
  const { busy, run } = useAction();

  useEffect(() => {
    if (data) setAbsent(new Set(data.royxat.filter((r) => r.holat === "absent").map((r) => r.id)));
    setResult(null);
  }, [data]);

  const toggle = (id: string, isAbsent: boolean) => {
    const s = new Set(absent);
    isAbsent ? s.add(id) : s.delete(id);
    setAbsent(s);
  };
  const save = () =>
    run(() => api<MarkResult>("/api/attendance", { body: { group: groupId, date, absent: [...absent] } }), "Davomat saqlandi")
      .then((r) => r && setResult(r));

  return (
    <div className="stack">
      <PageHead title={data?.guruh ?? "Davomat"}>
        <a className="btn" href="#/groups">← Guruhlar</a>
        <ExportButton kind="attendance_grid" label="Oylik davomat (Excel)" params={`group=${groupId}&month=${date.slice(0, 7)}`} />
      </PageHead>
      <Card
        title="Davomat"
        action={<input type="date" value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} style={{ width: "auto" }} />}
      >
        {data && !data.dars_kuni && <p><Badge tone="warn">Bu kun guruhning dars kuni emas</Badge></p>}
        {loading && !data ? <Loading /> : !data?.royxat.length ? <Empty>Guruhda faol o'quvchi yo'q</Empty> : (
          <>
            {data.royxat.map((r) => {
              const isAbs = absent.has(r.id);
              return (
                <div className="att-row" key={r.id}>
                  <span>{r.ism}</span>
                  <div className="toggle" role="group" aria-label={r.ism}>
                    <button className={`present ${!isAbs ? "on" : ""}`} onClick={() => toggle(r.id, false)}>Keldi</button>
                    <button className={`absent ${isAbs ? "on" : ""}`} onClick={() => toggle(r.id, true)}>Kelmadi</button>
                  </div>
                </div>
              );
            })}
            <div className="row" style={{ marginTop: 14 }}>
              <span className="muted spacer">{data.royxat.length - absent.size} keldi · {absent.size} kelmadi</span>
              <button className="primary" disabled={busy} onClick={save}>Saqlash</button>
            </div>
          </>
        )}
      </Card>
      {result && result.kelmaganlar.length > 0 && can("message_parents") && data && (
        <ParentMessages group={data.guruh} date={date} absent={result.kelmaganlar} />
      )}
    </div>
  );
}

function ParentMessages({ group, date, absent }: { group: string; date: string; absent: MarkResult["kelmaganlar"] }) {
  const d = date.split("-").reverse().join(".");
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(absent.map((s) => [s.id,
      `Assalomu alaykum! Farzandingiz ${s.full_name} bugun (${d}) "${group}" darsiga kelmadi. Iltimos, sababini markazga xabar bering. Rahmat!`])));
  const [sent, setSent] = useState<{ oquvchi: string; holat: string; telefonlar?: string[] }[] | null>(null);
  const { busy, run } = useAction();
  const linked = absent.filter((s) => s.ota_ona_ulangan);

  const send = () => {
    if (!confirm(`${linked.length} ta ota-onaga xabar yuborilsinmi?`)) return;
    run(() => api<{ natija: typeof sent }>("/api/message-parents", {
      body: { messages: linked.map((s) => ({ student: s.id, text: texts[s.id] })) },
    }), "Xabarlar yuborildi").then((r) => r && setSent(r.natija));
  };

  return (
    <Card title="Kelmaganlar ota-onasiga xabar">
      {absent.map((s) => (
        <div key={s.id} style={{ marginBottom: 12 }}>
          <div className="row" style={{ marginBottom: 6 }}>
            <b className="spacer">{s.full_name}</b>
            {s.ota_ona_ulangan ? <Badge tone="ok">Botga ulangan</Badge>
              : <Badge tone="warn">Ulanmagan{s.telefon ? ` · ${s.telefon}` : ""}</Badge>}
          </div>
          {s.ota_ona_ulangan && (
            <textarea value={texts[s.id]} onChange={(e) => setTexts({ ...texts, [s.id]: e.target.value })} />
          )}
        </div>
      ))}
      {sent ? (
        <div className="list">{sent.map((r, i) => <div className="list-item" key={i}><span>{r.oquvchi}</span><span className="muted">{r.holat}</span></div>)}</div>
      ) : linked.length > 0 ? (
        <div className="row"><span className="spacer muted small">Ulanmaganlarga telefon orqali qo'ng'iroq qiling.</span>
          <button className="primary" disabled={busy} onClick={send}>Xabar yuborish ({linked.length})</button></div>
      ) : <Empty>Ota-onalar botga ulanmagan: telefon orqali bog'laning.</Empty>}
    </Card>
  );
}

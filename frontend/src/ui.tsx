import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AuthError, type Me } from "./api";

// ---------- umumiy kontekst: kim kirgan, xabarnoma ----------
interface AppCtx {
  me: Me;
  can: (tool: string) => boolean;
  toast: (text: string, error?: boolean) => void;
  onAuthError: () => void;
}
export const Ctx = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(Ctx);

/** Ma'lumotni yuklaydi; xato bo'lsa xabar ko'rsatadi. reload() bilan qayta yuklanadi. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const { toast, onAuthError } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => {
        if (!alive) return;
        if (e instanceof AuthError) return onAuthError();
        setError(e.message);
        toast(e.message, true);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Tugma bosilganda bajariladigan amal (saqlash, yuborish). */
export function useAction() {
  const { toast, onAuthError } = useApp();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async <T,>(fn: () => Promise<T>, okText?: string): Promise<T | undefined> => {
      setBusy(true);
      try {
        const r = await fn();
        if (okText) toast(okText);
        return r;
      } catch (e: any) {
        if (e instanceof AuthError) onAuthError();
        else toast(e.message, true);
      } finally {
        setBusy(false);
      }
    },
    [toast, onAuthError],
  );
  return { busy, run };
}

// ---------- kichik komponentlar ----------
export function Card({ title, action, children, className = "" }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          {title ? <h2>{title}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "alert" | "good" }) {
  return (
    <div className={`card kpi ${tone ?? ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export const Badge = ({ tone = "", children }: { tone?: string; children: ReactNode }) => (
  <span className={`badge ${tone}`}>{children}</span>
);

export const Empty = ({ children = "Hozircha bo'sh" }: { children?: ReactNode }) => <div className="empty">{children}</div>;

export const Loading = () => <div className="empty">Yuklanmoqda…</div>;

export function Field({ label, children, full }: { label: string; children: ReactNode; full?: boolean }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      {label}
      {children}
    </label>
  );
}

export function Modal({ title, open, onClose, children }: {
  title: string; open: boolean; onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-btn" aria-label="Yopish" onClick={onClose}>✕</button>
      </div>
      <div className="modal-body">{open && children}</div>
    </dialog>
  );
}

export function CopyText({ text }: { text: string }) {
  const { toast } = useApp();
  return (
    <div className="row">
      <span className="copy spacer">{text}</span>
      <button className="small" onClick={() => navigator.clipboard.writeText(text).then(() => toast("Nusxalandi"))}>
        Nusxalash
      </button>
    </div>
  );
}

/** Excel faylini yuklab olish tugmasi */
export function ExportButton({ kind, label, params = "" }: { kind: string; label: string; params?: string }) {
  const { can } = useApp();
  if (!can("export_excel")) return null;
  return (
    <a className="btn" href={`/api/export/${kind}${params ? `?${params}` : ""}`}>
      ⬇ {label}
    </a>
  );
}

/** Sahifa sarlavhasi va o'ng tomondagi tugmalar */
export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="actions">{children}</div>
    </header>
  );
}

// ---------- jadval: kompyuterda jadval, telefonda kartochka ----------
export interface Col<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  right?: boolean;
  main?: boolean; // telefonda kartochka sarlavhasi
}

export function DataTable<T>({ cols, rows, onRow, empty = "Hozircha bo'sh", rowKey }: {
  cols: Col<T>[]; rows: T[]; onRow?: (r: T) => void; empty?: ReactNode; rowKey?: (r: T, i: number) => string;
}) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  return (
    <div className="table-wrap">
      <table className="stack-table">
        <thead>
          <tr>{cols.map((c) => <th key={c.key} className={c.right ? "right" : ""}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r, i) : i} className={onRow ? "click" : ""} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => (
                <td key={c.key} data-label={c.label} className={[c.right ? "right" : "", c.main ? "main" : ""].join(" ").trim()}>
                  {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tabs<K extends string>({ tabs, value, onChange }: {
  tabs: { key: K; label: string; show?: boolean }[]; value: K; onChange: (k: K) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.filter((t) => t.show !== false).map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key} className={value === t.key ? "on" : ""}
          onClick={() => onChange(t.key)}>{t.label}</button>
      ))}
    </div>
  );
}

export const Logo = ({ size = "" }: { size?: "" | "lg" }) => (
  <img src="/logo.webp" alt="Web Street IT Academy" className={`logo-img ${size}`} width={40} height={40} />
);

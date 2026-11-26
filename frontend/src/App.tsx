import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react";
import { api, type Me } from "./api";
import { Ctx, Logo } from "./ui";
import Home from "./pages/Home";
import Groups from "./pages/Groups";
import Students from "./pages/Students";
import Payments from "./pages/Payments";
import Leads from "./pages/Leads";
import Finance from "./pages/Finance";
import Teachers from "./pages/Teachers";
import Staff from "./pages/Staff";
import Chat from "./pages/Chat";
import Tasks from "./pages/Tasks";
import Content from "./pages/Content";
import Agents from "./pages/Agents";
import Quality from "./pages/Quality";
import Settings from "./pages/Settings";

export interface PageProps {
  param?: string; // masalan #/groups/<id> dagi id
}

interface Route {
  path: string;
  label: string;
  icon: string;
  group: string;
  page: ComponentType<PageProps>;
  show: (me: Me, can: (t: string) => boolean) => boolean;
}

// Menyu: har bir bo'lim faqat ruxsati bor odamga ko'rinadi (ruxsatlar serverda ham tekshiriladi)
const ROUTES: Route[] = [
  { path: "home", label: "Bosh sahifa", icon: "🏠", group: "Asosiy", page: Home, show: () => true },
  { path: "chat", label: "Jimi", icon: "💬", group: "Asosiy", page: Chat, show: () => true },
  { path: "tasks", label: "Vazifalar", icon: "✅", group: "Asosiy", page: Tasks, show: (_, c) => c("list_tasks") },
  { path: "groups", label: "Guruhlar", icon: "📚", group: "O'quv", page: Groups, show: (m, c) => c("overview") || m.role === "teacher" },
  { path: "students", label: "O'quvchilar", icon: "🎓", group: "O'quv", page: Students, show: (_, c) => c("find_student") },
  { path: "payments", label: "To'lovlar", icon: "💳", group: "O'quv", page: Payments, show: (_, c) => c("debtors") },
  { path: "teachers", label: "O'qituvchilar", icon: "👩‍🏫", group: "O'quv", page: Teachers, show: (_, c) => c("teacher_report") || c("my_report") },
  { path: "quality", label: "Sifat nazorati", icon: "🎯", group: "O'quv", page: Quality, show: (_, c) => c("quality_report") },
  { path: "content", label: "Kontent", icon: "🎬", group: "Marketing", page: Content, show: (_, c) => c("list_posts") || c("make_design") },
  { path: "leads", label: "Lidlar", icon: "📈", group: "Marketing", page: Leads, show: (_, c) => c("list_leads") },
  { path: "finance", label: "Moliya", icon: "💰", group: "Boshqaruv", page: Finance, show: (_, c) => c("finance_summary") },
  { path: "staff", label: "Xodimlar", icon: "👥", group: "Boshqaruv", page: Staff, show: (_, c) => c("list_staff") },
  { path: "agents", label: "AI jamoa", icon: "🤖", group: "Boshqaruv", page: Agents, show: (_, c) => c("list_agents") },
  { path: "settings", label: "Sozlamalar", icon: "⚙️", group: "Boshqaruv", page: Settings, show: (_, c) => c("get_settings") },
];

function useHash() {
  const [hash, setHash] = useState(() => location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const [path = "home", param] = hash.replace(/^#\/?/, "").split("/");
  return { path: path || "home", param };
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [menu, setMenu] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; text: string; error?: boolean }[]>([]);
  const { path, param } = useHash();

  useEffect(() => {
    api<Me>("/api/me").then(setMe).catch(() => setNeedLogin(true));
  }, []);
  useEffect(() => setMenu(false), [path, param]);
  useEffect(() => {
    document.body.style.overflow = menu ? "hidden" : "";
  }, [menu]);

  const toast = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 6000 : 3000);
  }, []);
  const onAuthError = useCallback(() => setNeedLogin(true), []);

  const ctx = useMemo(
    () => (me ? { me, can: (t: string) => me.tools.includes(t), toast, onAuthError } : null),
    [me, toast, onAuthError],
  );

  if (needLogin) return <Login />;
  if (!ctx || !me) return <div className="center-card"><div style={{ color: "#fff" }}>Yuklanmoqda…</div></div>;

  const visible = ROUTES.filter((r) => r.show(me, ctx.can));
  const route = visible.find((r) => r.path === path) ?? visible[0];
  const Page = route.page;
  const groups = [...new Set(visible.map((r) => r.group))];

  const logout = async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    setNeedLogin(true);
  };

  return (
    <Ctx.Provider value={ctx}>
      <div className="mobile-bar">
        <button className="menu-btn" aria-label="Menyu" aria-expanded={menu} onClick={() => setMenu(true)}>☰</button>
        <Logo />
        <b>{route.label}</b>
        <a href="#/chat" className="menu-btn btn" aria-label="Jimi" style={{ textDecoration: "none" }}>💬</a>
      </div>
      <div className={`backdrop ${menu ? "show" : ""}`} onClick={() => setMenu(false)} />
      <div id="app">
        <aside className={`sidebar ${menu ? "open" : ""}`} aria-label="Bo'limlar">
          <div className="brand">
            <Logo />
            <div>WS-Tizim<small>WEB STREET IT ACADEMY</small></div>
          </div>
          <nav id="nav">
            {groups.map((g) => (
              <div key={g}>
                <div className="nav-group">{g}</div>
                {visible.filter((r) => r.group === g).map((r) => (
                  <a key={r.path} href={`#/${r.path}`} className={r === route ? "active" : ""}>
                    <span className="ico" aria-hidden>{r.icon}</span>
                    {r.label}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <div className="me">
            <div className="me-name">{me.name}</div>
            <div className="muted small">{me.role_uz}</div>
            <button className="link small" onClick={logout}>Chiqish</button>
          </div>
        </aside>
        <main>
          <Page key={route.path + (param ?? "")} param={param} />
        </main>
      </div>
      <div id="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.error ? "error" : ""}`}>{t.text}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

function Login() {
  return (
    <div className="center-card">
      <div className="card">
        <div className="brand big"><Logo size="lg" /><div>WS-Tizim<small>WEB STREET IT ACADEMY</small></div></div>
        <h1>Panelga kirish</h1>
        <ol className="steps">
          <li>Telegramda o'z botingizni oching.</li>
          <li><b>/panel</b> deb yozing.</li>
          <li>Bot bergan havolani shu qurilmada bosing.</li>
        </ol>
        <p className="muted">
          Havola 15 daqiqa amal qiladi va faqat bir marta ishlaydi. Shundan keyin brauzer sizni 30 kun eslab qoladi.
        </p>
      </div>
    </div>
  );
}

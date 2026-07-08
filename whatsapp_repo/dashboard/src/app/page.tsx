"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DashboardData,
  fetchDashboard,
  login,
  subscribeEvents,
} from "@/lib/api";
import {
  KPICards,
  LancamentosTable,
  OfensoresChart,
  ProjecoesCard,
  SetorChart,
} from "@/components/Dashboard";

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("gastozap_token");
    if (saved) setToken(saved);
  }, []);

  const loadData = useCallback(async (t: string) => {
    const d = await fetchDashboard(t);
    setData(d);
  }, []);

  useEffect(() => {
    if (!token) return;
    loadData(token).catch(() => {
      localStorage.removeItem("gastozap_token");
      setToken(null);
    });
    const unsub = subscribeEvents(token, (d) => {
      setData(d);
      setLive(true);
      setTimeout(() => setLive(false), 3000);
    });
    return unsub;
  }, [token, loadData]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const t = await login(username, password);
      localStorage.setItem("gastozap_token", t);
      setToken(t);
    } catch {
      setError("Usuário ou senha incorretos");
    }
  }

  function handleLogout() {
    localStorage.removeItem("gastozap_token");
    setToken(null);
    setData(null);
  }

  if (!token) {
    return (
      <div className="login-container">
        <h1>GastoZap</h1>
        <p style={{ color: "#94a3b8" }}>Dashboard financeiro via WhatsApp</p>
        <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <input placeholder="Usuário" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            type="password"
            placeholder="Senha"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p style={{ color: "#f87171" }}>{error}</p>}
          <button type="submit">Entrar</button>
        </form>
      </div>
    );
  }

  if (!data) {
    return <div className="dashboard">Carregando...</div>;
  }

  return (
    <div className="dashboard">
      <div className="header">
        <div>
          <h1>GastoZap</h1>
          <p style={{ color: "#94a3b8" }}>Controle financeiro via WhatsApp</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {live && <span className="badge badge-live">Atualizado</span>}
          <button onClick={handleLogout} style={{ background: "#475569" }}>
            Sair
          </button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
        <KPICards kpis={data.kpis} />
        <div className="grid grid-2">
          <SetorChart porSetor={data.por_setor} />
          <OfensoresChart ofensores={data.ofensores} />
        </div>
        <ProjecoesCard projecoes={data.projecoes} />
        <LancamentosTable lancamentos={data.lancamentos_recentes} />
      </div>
    </div>
  );
}

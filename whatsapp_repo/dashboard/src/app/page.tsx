"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AdminLLMCost,
  DashboardData,
  DashboardFilters,
  fetchAdminLLMCost,
  fetchDashboard,
  login,
  subscribeEvents,
} from "@/lib/api";
import { CartoesPanel } from "@/components/Cartoes";
import {
  AdminLLMCostCard,
  CortesAnaliticosCard,
  FiltrosDashboard,
  KPICards,
  LancamentosTable,
  OfensoresChart,
  ProjecoesCard,
  SetorChart,
} from "@/components/Dashboard";

type Tab = "dashboard" | "cartoes" | "admin";

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [data, setData] = useState<DashboardData | null>(null);
  const [adminCost, setAdminCost] = useState<AdminLLMCost | null>(null);
  const [filters, setFilters] = useState<DashboardFilters>({});
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [live, setLive] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("gastozap_token");
    if (saved) setToken(saved);
  }, []);

  const loadData = useCallback(async (t: string, f: DashboardFilters = {}) => {
    const d = await fetchDashboard(t, f);
    setData(d);
  }, []);

  useEffect(() => {
    if (!token || activeTab !== "dashboard") return;
    setLoadError("");
    loadData(token, filters).catch((err) => {
      setLoadError(err instanceof Error ? err.message : "Falha ao carregar dashboard");
      setData(null);
    });
    const unsub = subscribeEvents(token, (d) => {
      setData(d);
      setLive(true);
      setTimeout(() => setLive(false), 3000);
    }, filters);
    return unsub;
  }, [token, filters, loadData, activeTab]);

  useEffect(() => {
    if (!token || activeTab !== "admin") return;
    fetchAdminLLMCost(token)
      .then(setAdminCost)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Falha ao carregar painel admin"));
  }, [token, activeTab]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const t = await login(username, password);
      localStorage.setItem("gastozap_token", t);
      setToken(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao entrar");
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

  return (
    <div className="dashboard">
      <div className="header">
        <div>
          <h1>GastoZap</h1>
          <p style={{ color: "#94a3b8" }}>Controle financeiro via WhatsApp</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {live && activeTab === "dashboard" && <span className="badge badge-live">Atualizado</span>}
          <button onClick={handleLogout} className="btn-secondary">
            Sair
          </button>
        </div>
      </div>

      <div className="tabs">
        <button
          type="button"
          className={`tab ${activeTab === "dashboard" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("dashboard")}
        >
          Visão geral
        </button>
        <button
          type="button"
          className={`tab ${activeTab === "cartoes" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("cartoes")}
        >
          Cartões
        </button>
        <button
          type="button"
          className={`tab ${activeTab === "admin" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("admin")}
        >
          Admin
        </button>
      </div>

      {activeTab === "dashboard" && (
        <>
          {!data ? (
            <div style={{ padding: "2rem 0" }}>
              {loadError ? (
                <>
                  <p style={{ color: "#f87171" }}>{loadError}</p>
                  <button onClick={handleLogout}>Voltar ao login</button>
                </>
              ) : (
                <p style={{ color: "#94a3b8" }}>Carregando...</p>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
              <KPICards kpis={data.kpis} />
              <FiltrosDashboard filters={filters} onChange={setFilters} />
              <CortesAnaliticosCard cortes={data.cortes} />
              <div className="grid grid-2">
                <SetorChart porSetor={data.por_setor} />
                <OfensoresChart ofensores={data.ofensores} />
              </div>
              <ProjecoesCard projecoes={data.projecoes} />
              <LancamentosTable lancamentos={data.lancamentos_recentes} />
            </div>
          )}
        </>
      )}

      {activeTab === "cartoes" && <CartoesPanel token={token} />}

      {activeTab === "admin" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {adminCost ? (
            <AdminLLMCostCard data={adminCost} />
          ) : (
            <p style={{ color: "#94a3b8" }}>Carregando custos do LLM...</p>
          )}
        </div>
      )}
    </div>
  );
}

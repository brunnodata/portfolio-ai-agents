"use client";

import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js";
import { Bar, Doughnut } from "react-chartjs-2";
import type { DashboardData } from "@/lib/api";
import { formatBRL } from "@/lib/api";

ChartJS.register(CategoryScale, LinearScale, BarElement, ArcElement, Title, Tooltip, Legend);

export function KPICards({ kpis }: { kpis: DashboardData["kpis"] }) {
  const variacao =
    kpis.total_mes_anterior > 0
      ? ((kpis.total_mes - kpis.total_mes_anterior) / kpis.total_mes_anterior) * 100
      : 0;

  return (
    <div className="grid grid-4">
      <div className="card">
        <div className="kpi-value">{formatBRL(kpis.total_mes)}</div>
        <div className="kpi-label">Total do mês</div>
      </div>
      <div className="card">
        <div className="kpi-value">{kpis.qtd_lancamentos_mes}</div>
        <div className="kpi-label">Lançamentos</div>
      </div>
      <div className="card">
        <div className="kpi-value">{formatBRL(kpis.media_diaria)}</div>
        <div className="kpi-label">Média diária</div>
      </div>
      <div className="card">
        <div className="kpi-value">{formatBRL(kpis.projecao_mes)}</div>
        <div className="kpi-label">
          Projeção do mês {variacao !== 0 && `(${variacao > 0 ? "+" : ""}${variacao.toFixed(0)}%)`}
        </div>
      </div>
    </div>
  );
}

export function SetorChart({ porSetor }: { porSetor: DashboardData["por_setor"] }) {
  const labels = porSetor.map((s) => s.setor);
  const values = porSetor.map((s) => s.total);

  return (
    <div className="card">
      <h3 style={{ marginBottom: "1rem" }}>Gastos por setor</h3>
      <Bar
        data={{
          labels,
          datasets: [
            {
              label: "R$",
              data: values,
              backgroundColor: "#3b82f6",
            },
          ],
        }}
        options={{
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            y: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } },
            x: { ticks: { color: "#94a3b8" }, grid: { display: false } },
          },
        }}
      />
    </div>
  );
}

export function OfensoresChart({ ofensores }: { ofensores: DashboardData["ofensores"] }) {
  if (!ofensores.length) return null;

  return (
    <div className="card">
      <h3 style={{ marginBottom: "1rem" }}>Maiores ofensores</h3>
      <Doughnut
        data={{
          labels: ofensores.map((o) => o.setor),
          datasets: [
            {
              data: ofensores.map((o) => o.total),
              backgroundColor: ["#ef4444", "#f97316", "#eab308"],
            },
          ],
        }}
        options={{
          responsive: true,
          plugins: { legend: { position: "bottom", labels: { color: "#94a3b8" } } },
        }}
      />
    </div>
  );
}

export function LancamentosTable({ lancamentos }: { lancamentos: DashboardData["lancamentos_recentes"] }) {
  return (
    <div className="card">
      <h3 style={{ marginBottom: "1rem" }}>Lançamentos recentes</h3>
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Estabelecimento</th>
            <th>Setor</th>
            <th>Tipo</th>
            <th>Valor</th>
            <th>Origem</th>
          </tr>
        </thead>
        <tbody>
          {lancamentos.map((l) => (
            <tr key={l.id}>
              <td>{new Date(l.data_hora).toLocaleDateString("pt-BR")}</td>
              <td>{l.estabelecimento}</td>
              <td><span className="badge">{l.setor}</span></td>
              <td>{l.tipo.replace("_", " ")}</td>
              <td>{formatBRL(l.valor)}</td>
              <td>{l.origem}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProjecoesCard({ projecoes }: { projecoes: DashboardData["projecoes"] }) {
  if (!projecoes.length) return null;

  return (
    <div className="card">
      <h3 style={{ marginBottom: "1rem" }}>Projeções</h3>
      <ul style={{ listStyle: "none" }}>
        {projecoes.map((p, i) => (
          <li key={i} style={{ padding: "0.4rem 0", borderBottom: "1px solid #334155" }}>
            <strong>{p.mes}</strong> — {formatBRL(p.valor)}{" "}
            <span className="badge">{p.tipo.replace(/_/g, " ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CortesAnaliticosCard({ cortes }: { cortes: DashboardData["cortes"] }) {
  return (
    <div className="card">
      <h3 style={{ marginBottom: "1rem" }}>Cortes analíticos</h3>
      <div className="grid grid-4" style={{ marginBottom: "1rem" }}>
        <div>
          <div className="kpi-value" style={{ fontSize: "1.2rem" }}>
            {formatBRL(cortes.projecao_proximo_mes)}
          </div>
          <div className="kpi-label">Projeção próximo mês</div>
        </div>
        <div>
          <div className="kpi-value" style={{ fontSize: "1.2rem" }}>
            {formatBRL(cortes.continua_proximo_mes)}
          </div>
          <div className="kpi-label">Continua (assin./fixo/parc.)</div>
        </div>
        <div>
          <div className="kpi-value" style={{ fontSize: "1.2rem" }}>
            {formatBRL(cortes.nao_volta_proximo_mes)}
          </div>
          <div className="kpi-label">À vista (não volta)</div>
        </div>
        <div>
          <div className="kpi-value" style={{ fontSize: "1.2rem" }}>
            {formatBRL(cortes.recorrentes_estimados)}
          </div>
          <div className="kpi-label">Recorrentes (mercado/gas./lanche)</div>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Tipo</th>
            <th>Total mês</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {cortes.por_tipo.map((t) => (
            <tr key={t.tipo}>
              <td>{t.tipo.replace(/_/g, " ")}</td>
              <td>{formatBRL(t.total)}</td>
              <td>{t.percentual.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FiltrosDashboard({
  filters,
  onChange,
}: {
  filters: { setor?: string; tipo?: string };
  onChange: (filters: { setor?: string; tipo?: string }) => void;
}) {
  return (
    <div className="card" style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", flex: 1, minWidth: "140px" }}>
        <span className="kpi-label">Setor</span>
        <select
          className="filter-select"
          value={filters.setor || ""}
          onChange={(e) => onChange({ ...filters, setor: e.target.value || undefined })}
        >
          <option value="">Todos</option>
          {["mercado", "lanche", "gasolina", "ferramenta", "cursos", "viagem", "restaurante", "outros"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", flex: 1, minWidth: "140px" }}>
        <span className="kpi-label">Tipo</span>
        <select
          className="filter-select"
          value={filters.tipo || ""}
          onChange={(e) => onChange({ ...filters, tipo: e.target.value || undefined })}
        >
          <option value="">Todos</option>
          {["a_vista", "assinatura", "fixo", "parcelado"].map((t) => (
            <option key={t} value={t}>{t.replace("_", " ")}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

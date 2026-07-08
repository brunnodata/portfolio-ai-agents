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
            <strong>{p.mes}</strong> — {formatBRL(p.valor)} <span className="badge">{p.tipo}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

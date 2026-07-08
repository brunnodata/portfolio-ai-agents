const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DashboardKPIs {
  total_mes: number;
  total_mes_anterior: number;
  qtd_lancamentos_mes: number;
  media_diaria: number;
  projecao_mes: number;
}

export interface SetorGasto {
  setor: string;
  total: number;
  percentual: number;
}

export interface Lancamento {
  id: number;
  estabelecimento: string;
  setor: string;
  tipo: string;
  valor: number;
  parcelas: string | null;
  data_hora: string;
  origem: string;
}

export interface DashboardData {
  kpis: DashboardKPIs;
  por_setor: SetorGasto[];
  lancamentos_recentes: Lancamento[];
  projecoes: { mes: string; valor: number; tipo: string }[];
  ofensores: SetorGasto[];
}

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("Credenciais inválidas");
  const data = await res.json();
  return data.access_token;
}

export async function fetchDashboard(token: string): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/dashboard`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Falha ao carregar dashboard");
  return res.json();
}

export function formatBRL(value: number): string {
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function subscribeEvents(token: string, onData: (data: DashboardData) => void): () => void {
  const source = new EventSource(`${API_URL}/api/events?token=${token}`);

  source.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      if (parsed.dashboard) {
        onData(parsed.dashboard);
      } else if (parsed.type === "refresh") {
        fetchDashboard(token).then(onData).catch(console.error);
      }
    } catch (e) {
      console.error(e);
    }
  };

  return () => source.close();
}

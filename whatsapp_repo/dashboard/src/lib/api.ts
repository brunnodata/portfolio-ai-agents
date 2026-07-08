// No browser usa proxy same-origin (/api-proxy) para evitar CORS no Easypanel.
// No build/server usa NEXT_PUBLIC_API_URL apontando para o backend.
export const API_URL =
  typeof window !== "undefined"
    ? "/api-proxy"
    : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  projecoes: { mes: string; valor: number; tipo: string; descricao?: string }[];
  ofensores: SetorGasto[];
  cortes: {
    por_tipo: { tipo: string; total: number; percentual: number }[];
    continua_proximo_mes: number;
    nao_volta_proximo_mes: number;
    recorrentes_estimados: number;
    projecao_proximo_mes: number;
  };
}

export interface DashboardFilters {
  setor?: string;
  tipo?: string;
  mes?: number;
  ano?: number;
}

export async function login(username: string, password: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("Não foi possível conectar à API. Refaça o deploy do front com NEXT_PUBLIC_API_URL.");
  }
  if (res.status === 401) throw new Error("Usuário ou senha incorretos");
  if (!res.ok) throw new Error(`Erro ${res.status} ao autenticar`);
  const data = await res.json();
  return data.access_token;
}

export async function fetchDashboard(token: string, filters: DashboardFilters = {}): Promise<DashboardData> {
  const params = new URLSearchParams();
  if (filters.setor) params.set("setor", filters.setor);
  if (filters.tipo) params.set("tipo", filters.tipo);
  if (filters.mes) params.set("mes", String(filters.mes));
  if (filters.ano) params.set("ano", String(filters.ano));
  const qs = params.toString();
  const res = await fetch(`${API_URL}/api/dashboard${qs ? `?${qs}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Falha ao carregar dashboard");
  return res.json();
}

export function formatBRL(value: number): string {
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function subscribeEvents(
  token: string,
  onData: (data: DashboardData) => void,
  filters: DashboardFilters = {}
): () => void {
  const source = new EventSource(`${API_URL}/api/events?token=${token}`);

  source.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      if (parsed.dashboard) {
        onData(parsed.dashboard);
      } else if (parsed.type === "refresh") {
        fetchDashboard(token, filters).then(onData).catch(console.error);
      }
    } catch (e) {
      console.error(e);
    }
  };

  return () => source.close();
}

function resolveApiUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (configured) return configured;
  if (typeof window !== "undefined") return "/api-proxy";
  return "http://localhost:8000";
}

export const API_URL = resolveApiUrl();

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
  item: string | null;
  estabelecimento: string;
  setor: string;
  tipo: string;
  valor: number;
  parcelas: string | null;
  data_hora: string;
  origem: string;
}

export interface AdminLLMCost {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_brl: number;
  daily_budget_brl: number;
  budget_used_percent: number;
  budget_remaining_brl: number;
  updated_at: string | null;
  rates: {
    input_per_1k_brl: number;
    output_per_1k_brl: number;
  };
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

export interface Cartao {
  id: number;
  banco_origem: string;
  ultimos_4_digitos: string;
  vencimento: string | null;
  bandeira: string | null;
  limite_total: number | null;
  limite_em_uso: number | null;
  limite_restante: number | null;
  qt_assinaturas: number;
  valores_futuros: Record<string, number>;
  cartao_padrao: string;
  obs: string | null;
}

export interface CartaoInput {
  banco_origem: string;
  ultimos_4_digitos: string;
  vencimento?: string;
  bandeira?: string;
  limite_total?: number;
  cartao_padrao?: string;
  obs?: string;
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
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Erro ${res.status} ao carregar dashboard`);
  }
  return res.json();
}

export async function fetchAdminLLMCost(token: string): Promise<AdminLLMCost> {
  const res = await fetch(`${API_URL}/api/admin/llm-cost`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Erro ${res.status} ao carregar custos`);
  }
  return res.json();
}

async function apiFetch(token: string, path: string, init: RequestInit = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      detail = JSON.parse(body).detail || body;
    } catch {
      /* use raw body */
    }
    throw new Error(detail || `Erro ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function fetchCartoes(token: string): Promise<Cartao[]> {
  return apiFetch(token, "/api/cartoes");
}

export async function createCartao(token: string, data: CartaoInput): Promise<Cartao> {
  return apiFetch(token, "/api/cartoes", { method: "POST", body: JSON.stringify(data) });
}

export async function updateCartao(token: string, id: number, data: Partial<CartaoInput>): Promise<Cartao> {
  return apiFetch(token, `/api/cartoes/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function setCartaoPadrao(token: string, id: number): Promise<Cartao> {
  return apiFetch(token, `/api/cartoes/${id}/padrao`, { method: "PATCH" });
}

export async function deleteCartao(token: string, id: number): Promise<void> {
  await apiFetch(token, `/api/cartoes/${id}`, { method: "DELETE" });
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

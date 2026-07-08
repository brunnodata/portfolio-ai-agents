"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Cartao,
  CartaoInput,
  createCartao,
  deleteCartao,
  fetchCartoes,
  formatBRL,
  setCartaoPadrao,
  updateCartao,
} from "@/lib/api";

const EMPTY_FORM: CartaoInput = {
  banco_origem: "",
  ultimos_4_digitos: "",
  vencimento: "",
  bandeira: "",
  limite_total: undefined,
  cartao_padrao: "nao",
  obs: "",
};

function limiteDisponivel(c: Cartao): number | null {
  if (c.limite_total == null) return null;
  if (c.limite_restante != null) return c.limite_restante;
  return c.limite_total - (c.limite_em_uso ?? 0);
}

function formatVencimento(value: string | null) {
  if (!value) return "—";
  const [y, m] = value.split("-");
  return `${m}/${y}`;
}

function isVencendo(value: string | null) {
  if (!value) return false;
  const venc = new Date(value);
  const limite = new Date();
  limite.setMonth(limite.getMonth() + 3);
  return venc <= limite;
}

export function CartoesPanel({ token }: { token: string }) {
  const [cartoes, setCartoes] = useState<Cartao[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<CartaoInput>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCartoes(await fetchCartoes(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar cartões");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function openEdit(cartao: Cartao) {
    setEditingId(cartao.id);
    setForm({
      banco_origem: cartao.banco_origem,
      ultimos_4_digitos: cartao.ultimos_4_digitos,
      vencimento: cartao.vencimento || "",
      bandeira: cartao.bandeira || "",
      limite_total: cartao.limite_total ?? undefined,
      cartao_padrao: cartao.cartao_padrao,
      obs: cartao.obs || "",
    });
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload: CartaoInput = {
        ...form,
        ultimos_4_digitos: form.ultimos_4_digitos.slice(-4),
        vencimento: form.vencimento || undefined,
        bandeira: form.bandeira || undefined,
        obs: form.obs || undefined,
      };
      if (editingId) {
        await updateCartao(token, editingId, payload);
      } else {
        await createCartao(token, payload);
      }
      closeForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao salvar cartão");
    } finally {
      setSaving(false);
    }
  }

  async function handleSetPadrao(id: number) {
    setError("");
    try {
      await setCartaoPadrao(token, id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao definir cartão padrão");
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remover este cartão? Só é possível se não houver lançamentos vinculados.")) return;
    setError("");
    try {
      await deleteCartao(token, id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao remover cartão");
    }
  }

  if (loading) {
    return <p style={{ color: "#94a3b8" }}>Carregando cartões...</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ fontSize: "1.25rem" }}>Cartões cadastrados</h2>
          <p style={{ color: "#94a3b8", fontSize: "0.9rem" }}>
            Cartões adicionados pelo WhatsApp ou pelo painel aparecem aqui.
          </p>
        </div>
        <button onClick={openCreate}>+ Novo cartão</button>
      </div>

      {error && <p style={{ color: "#f87171" }}>{error}</p>}

      {showForm && (
        <div className="card">
          <h3 style={{ marginBottom: "1rem" }}>{editingId ? "Editar cartão" : "Novo cartão"}</h3>
          <form onSubmit={handleSubmit} className="form-grid">
            <label>
              Banco
              <input
                required
                value={form.banco_origem}
                onChange={(e) => setForm({ ...form, banco_origem: e.target.value })}
                placeholder="Nubank"
              />
            </label>
            <label>
              Últimos 4 dígitos
              <input
                required
                maxLength={4}
                value={form.ultimos_4_digitos}
                onChange={(e) => setForm({ ...form, ultimos_4_digitos: e.target.value.replace(/\D/g, "") })}
                placeholder="1234"
              />
            </label>
            <label>
              Vencimento
              <input
                type="month"
                value={form.vencimento?.slice(0, 7) || ""}
                onChange={(e) => setForm({ ...form, vencimento: e.target.value ? `${e.target.value}-01` : "" })}
              />
            </label>
            <label>
              Bandeira
              <input
                value={form.bandeira || ""}
                onChange={(e) => setForm({ ...form, bandeira: e.target.value })}
                placeholder="Visa, Mastercard..."
              />
            </label>
            <label>
              Limite total
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.limite_total ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    limite_total: e.target.value ? Number(e.target.value) : undefined,
                  })
                }
                placeholder="5000"
              />
            </label>
            <label>
              Cartão padrão
              <select
                className="filter-select"
                value={form.cartao_padrao || "nao"}
                onChange={(e) => setForm({ ...form, cartao_padrao: e.target.value })}
              >
                <option value="nao">Não</option>
                <option value="sim">Sim</option>
              </select>
            </label>
            <label style={{ gridColumn: "1 / -1" }}>
              Observações
              <input
                value={form.obs || ""}
                onChange={(e) => setForm({ ...form, obs: e.target.value })}
                placeholder="Opcional"
              />
            </label>
            <div style={{ gridColumn: "1 / -1", display: "flex", gap: "0.5rem" }}>
              <button type="submit" disabled={saving}>
                {saving ? "Salvando..." : "Salvar"}
              </button>
              <button type="button" className="btn-secondary" onClick={closeForm}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {cartoes.length === 0 ? (
          <p style={{ color: "#94a3b8" }}>Nenhum cartão cadastrado ainda.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Cartão</th>
                <th>Vencimento</th>
                <th>Limite</th>
                <th>Em uso</th>
                <th>Disponível</th>
                <th>Projeções</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {cartoes.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                      <strong>
                        {c.banco_origem} ****{c.ultimos_4_digitos}
                      </strong>
                      <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>
                        {c.bandeira || "Bandeira não informada"}
                      </span>
                      {c.cartao_padrao === "sim" && <span className="badge badge-default">Padrão</span>}
                    </div>
                  </td>
                  <td>
                    <span className={isVencendo(c.vencimento) ? "text-warning" : ""}>
                      {formatVencimento(c.vencimento)}
                    </span>
                  </td>
                  <td>{c.limite_total != null ? formatBRL(c.limite_total) : "—"}</td>
                  <td>{c.limite_em_uso != null ? formatBRL(c.limite_em_uso) : "—"}</td>
                  <td>
                    {(() => {
                      const disp = limiteDisponivel(c);
                      return disp != null ? formatBRL(disp) : "—";
                    })()}
                  </td>
                  <td>
                    {Object.keys(c.valores_futuros).length === 0
                      ? "—"
                      : Object.entries(c.valores_futuros)
                          .map(([mes, val]) => `${mes}: ${formatBRL(val)}`)
                          .join(", ")}
                  </td>
                  <td>
                    <div className="table-actions">
                      <button type="button" className="btn-secondary btn-sm" onClick={() => openEdit(c)}>
                        Editar
                      </button>
                      {c.cartao_padrao !== "sim" && (
                        <button type="button" className="btn-secondary btn-sm" onClick={() => handleSetPadrao(c.id)}>
                          Tornar padrão
                        </button>
                      )}
                      <button type="button" className="btn-danger btn-sm" onClick={() => handleDelete(c.id)}>
                        Excluir
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

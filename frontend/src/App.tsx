import React, { useState, useEffect, useCallback } from 'react';
import { PluggyConnect } from 'react-pluggy-connect';
import {
  CreditCard,
  TrendingUp,
  ListFilter,
  Target,
  FileText,
  Landmark,
  Settings,
  RefreshCw,
  Plus,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Clock,
  Search,
  Send,
  Trash2,
  ShieldCheck,
  Edit3,
  X,
  ChevronRight,
  Info,
  Mail,
} from 'lucide-react';

type PageId = 'dashboard' | 'transactions' | 'budgets' | 'reports' | 'connections' | 'settings';

export default function App() {
  const [activePage, setActivePage] = useState<PageId>('dashboard');
  const [period, setPeriod] = useState<'today' | 'week' | 'month' | 'custom'>('month');
  const [customStart, setCustomStart] = useState('2026-10-01');
  const [customEnd, setCustomEnd] = useState('2026-10-26');

  const [dashboard, setDashboard] = useState<any>(null);
  const [txData, setTxData] = useState<any>({ total: 0, items: [] });
  const [catData, setCatData] = useState<any>({ categories: [], rules: [] });
  const [reportsData, setReportsData] = useState<any>(null);
  const [viability, setViability] = useState<any>(null);
  const [settings, setSettings] = useState<any>(null);

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [connectToken, setConnectToken] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; type: 'ok' | 'warn' | 'err' } | null>(null);

  // Filters for Transactions Page
  const [txSearch, setTxSearch] = useState('');
  const [txCatFilter, setTxCatFilter] = useState<string>('');
  const [txStatusFilter, setTxStatusFilter] = useState<string>('');
  const [txTypeFilter, setTxTypeFilter] = useState<string>('');
  const [uncatOnly, setUncatOnly] = useState(false);

  // Manual / Quick Test Purchase Modal
  const [newTxModal, setNewTxModal] = useState(false);
  const [newTxForm, setNewTxForm] = useState({
    description: 'IFD*IFOOD COM AGENCIA',
    amount_reais: '100.00',
    status: 'POSTED',
    tx_type: 'EXPENSE',
    card_label: 'Santander Unique Black',
  });

  // Category Reclassify Modal
  const [reclassifyingTx, setReclassifyingTx] = useState<any | null>(null);
  const [reclassCatId, setReclassCatId] = useState<number>(1);
  const [createRuleOnReclass, setCreateRuleOnReclass] = useState(true);
  const [rulePatternOnReclass, setRulePatternOnReclass] = useState('');

  // Budget Create/Edit Modal
  const [budgetModal, setBudgetModal] = useState(false);
  const [editingBudget, setEditingBudget] = useState<any | null>(null);
  const [budgetForm, setBudgetForm] = useState({
    category_id: 1,
    name: '',
    limit_reais: '500.00',
    include_pending: false,
    alert_thresholds: '50,75,90,100',
  });

  // New Rule Form
  const [ruleForm, setRuleForm] = useState({
    category_id: 1,
    pattern: '',
    match_field: 'ANY',
    priority: 100,
  });

  const notify = (text: string, type: 'ok' | 'warn' | 'err' = 'ok') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 5000);
  };

  const loadDashboard = useCallback(async () => {
    const params = new URLSearchParams({ period });
    if (period === 'custom') {
      params.set('start_date', customStart);
      params.set('end_date', customEnd);
    }
    const res = await fetch(`/api/dashboard?${params.toString()}`);
    if (res.ok) setDashboard(await res.json());
  }, [period, customStart, customEnd]);

  const loadTransactions = useCallback(async () => {
    const params = new URLSearchParams();
    if (txSearch) params.set('search', txSearch);
    if (txCatFilter) params.set('category_id', txCatFilter);
    if (txStatusFilter) params.set('status', txStatusFilter);
    if (txTypeFilter) params.set('tx_type', txTypeFilter);
    if (uncatOnly) params.set('uncategorized_only', 'true');
    const res = await fetch(`/api/transactions?${params.toString()}`);
    if (res.ok) setTxData(await res.json());
  }, [txSearch, txCatFilter, txStatusFilter, txTypeFilter, uncatOnly]);

  const loadSupportingData = useCallback(async () => {
    const [cRes, rRes, vRes, sRes] = await Promise.all([
      fetch('/api/categories'),
      fetch('/api/reports'),
      fetch('/api/pluggy/viability'),
      fetch('/api/settings'),
    ]);
    if (cRes.ok) setCatData(await cRes.json());
    if (rRes.ok) setReportsData(await rRes.json());
    if (vRes.ok) setViability(await vRes.json());
    if (sRes.ok) setSettings(await sRes.json());
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([loadDashboard(), loadTransactions(), loadSupportingData()]);
    } finally {
      setLoading(false);
    }
  }, [loadDashboard, loadTransactions, loadSupportingData]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const handleConnectPluggyWidget = async () => {
    try {
      const res = await fetch('/api/pluggy/connect-token', { method: 'POST' });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Erro ao gerar Connect Token');
      setConnectToken(j.accessToken);
    } catch (e: any) {
      notify(e.message, 'err');
    }
  };

  const handleConnectSandboxNow = async () => {
    setSyncing(true);
    try {
      const res = await fetch('/api/pluggy/connect-sandbox', { method: 'POST' });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Falha ao sincronizar Sandbox');
      notify(
        `Pluggy Bank Sandbox sincronizado! ${j.accounts_synced} contas, ${j.transactions_inserted} novas transações e ${j.transactions_deduplicated} reconciliadas.`,
        'ok'
      );
      await refreshAll();
    } catch (e: any) {
      notify(e.message, 'err');
    } finally {
      setSyncing(false);
    }
  };

  const handleManualSyncItem = async (itemId: string) => {
    setSyncing(true);
    try {
      const res = await fetch('/api/pluggy/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pluggy_item_id: itemId }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Falha na sincronização');
      notify(
        `Sincronização concluída: ${j.transactions_inserted} novas, ${j.transactions_updated} atualizadas, ${j.transactions_deduplicated} já existentes.`,
        'ok'
      );
      await refreshAll();
    } catch (e: any) {
      notify(e.message, 'err');
    } finally {
      setSyncing(false);
    }
  };

  const handleDisconnectBank = async (connId: number, name: string) => {
    if (!window.confirm(`Desconectar ${name} e remover as transações sincronizadas desta instituição?`)) return;
    const res = await fetch(`/api/pluggy/connections/${connId}?delete_transactions=true`, { method: 'DELETE' });
    if (res.ok) {
      notify(`Conexão com ${name} revogada com sucesso.`, 'warn');
      await refreshAll();
    }
  };

  const handleCreateTransaction = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await fetch('/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...newTxForm,
        amount_reais: parseFloat(newTxForm.amount_reais.replace(',', '.')) || 0,
      }),
    });
    const j = await res.json();
    if (res.ok) {
      setNewTxModal(false);
      notify(
        `Transação de ${j.amount_brl} registrada (${j.applied_rule_name || 'Sem regra'}). Orçamentos recalculados!`,
        'ok'
      );
      await refreshAll();
    }
  };

  const handleReclassifySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reclassifyingTx) return;
    const res = await fetch(`/api/transactions/${reclassifyingTx.id}/category`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        category_id: reclassCatId,
        create_rule: createRuleOnReclass,
        rule_pattern: rulePatternOnReclass,
        rule_match_field: 'ANY',
      }),
    });
    const j = await res.json();
    if (res.ok) {
      setReclassifyingTx(null);
      notify(
        `Categoria atualizada! ${j.reclassified_count ? `${j.reclassified_count} outras transações também foram reclassificadas pela nova regra.` : ''}`,
        'ok'
      );
      await refreshAll();
    }
  };

  const handleSaveBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    if (editingBudget) {
      await fetch(`/api/budgets/${editingBudget.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: budgetForm.name,
          limit_reais: parseFloat(budgetForm.limit_reais.replace(',', '.')) || 0,
          include_pending: budgetForm.include_pending,
          alert_thresholds: budgetForm.alert_thresholds,
        }),
      });
      notify('Orçamento atualizado e recalculado!', 'ok');
    } else {
      await fetch('/api/budgets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category_id: Number(budgetForm.category_id),
          name: budgetForm.name,
          limit_reais: parseFloat(budgetForm.limit_reais.replace(',', '.')) || 0,
          include_pending: budgetForm.include_pending,
          alert_thresholds: budgetForm.alert_thresholds,
        }),
      });
      notify('Orçamento salvo com sucesso!', 'ok');
    }
    setBudgetModal(false);
    setEditingBudget(null);
    await refreshAll();
  };

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await fetch('/api/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ruleForm),
    });
    const j = await res.json();
    if (res.ok) {
      setRuleForm({ ...ruleForm, pattern: '' });
      notify(`Regra criada! ${j.reclassified} transações foram categorizadas automaticamente.`, 'ok');
      await refreshAll();
    }
  };

  const handleTriggerReport = async (type: 'daily' | 'weekly') => {
    const res = await fetch(`/api/reports/generate/${type}`, { method: 'POST' });
    const j = await res.json();
    if (res.ok) {
      const deliv = j.deliveries?.[0];
      notify(
        deliv?.status === 'SENT'
          ? `Relatório enviado com sucesso para ${deliv.recipient}!`
          : `Relatório gerado e registrado! Status de entrega: ${deliv?.status || 'Gerado'}.`,
        'ok'
      );
      await refreshAll();
    }
  };

  if (loading || !dashboard) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin text-teal-400" />
          Carregando plataforma financeira...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col lg:flex-row">
      {/* Pluggy Official Connect Modal */}
      {connectToken && (
        <PluggyConnect
          connectToken={connectToken}
          includeSandbox={true}
          onSuccess={async (itemData: any) => {
            setConnectToken(null);
            if (itemData?.item?.id) {
              await handleManualSyncItem(itemData.item.id);
            }
          }}
          onError={(err: any) => {
            console.error(err);
            notify('Falha ao autenticar no widget da Pluggy.', 'err');
          }}
          onClose={() => setConnectToken(null)}
        />
      )}

      {/* Toast Feedback */}
      {toast && (
        <div className="fixed bottom-5 right-5 z-50 max-w-md rounded-xl border px-4 py-3 shadow-xl bg-slate-900 border-slate-700 text-sm flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full shrink-0 ${
              toast.type === 'err' ? 'bg-red-500' : toast.type === 'warn' ? 'bg-amber-400' : 'bg-emerald-400'
            }`}
          />
          <span>{toast.text}</span>
        </div>
      )}

      {/* Sidebar Navigation */}
      <aside className="w-full lg:w-64 bg-slate-900 border-b lg:border-b-0 lg:border-r border-slate-800 shrink-0 flex flex-col justify-between">
        <div>
          <div className="p-5 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-teal-600 flex items-center justify-center text-white font-bold">
                <CreditCard className="w-5 h-5" />
              </div>
              <div>
                <h1 className="font-bold text-sm text-white leading-tight">Controle Financeiro</h1>
                <span className="text-[11px] text-slate-400 block">Open Finance • {dashboard.user.name}</span>
              </div>
            </div>
          </div>

          <nav aria-label="Menu Principal" className="p-3 flex lg:flex-col gap-1 overflow-x-auto">
            {[
              { id: 'dashboard', label: '1. Dashboard', icon: TrendingUp },
              { id: 'transactions', label: '2. Transações', icon: ListFilter },
              { id: 'budgets', label: '3. Orçamentos & Regras', icon: Target },
              { id: 'reports', label: '4. Relatórios Passivos', icon: FileText },
              { id: 'connections', label: '5. Conexões Bancárias', icon: Landmark },
              { id: 'settings', label: '6. Configurações & LGPD', icon: Settings },
            ].map((item) => {
              const Icon = item.icon;
              const active = activePage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActivePage(item.id as PageId)}
                  className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-lg text-xs sm:text-sm font-medium transition whitespace-nowrap cursor-pointer ${
                    active
                      ? 'bg-teal-600/15 text-teal-300 border border-teal-500/30'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="hidden lg:block p-4 border-t border-slate-800 text-xs text-slate-400 space-y-2">
          <div className="flex items-center justify-between">
            <span>Fuso Horário:</span>
            <span className="font-mono text-slate-300">America/Sao_Paulo</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Última Sync:</span>
            <span className="text-slate-300">{dashboard.sync_status.last_sync_at || 'Nunca'}</span>
          </div>
          <button
            onClick={() => setNewTxModal(true)}
            className="w-full mt-2 py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium flex items-center justify-center gap-1.5 transition cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            Registrar / Testar Compra
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full space-y-6">
        {/* Global Sync / Outdated Warning Banner */}
        {dashboard.sync_status.sync_warning && (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-amber-950/40 border border-amber-500/40 text-amber-200 text-xs sm:text-sm"
          >
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>{dashboard.sync_status.sync_warning}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleConnectSandboxNow}
                disabled={syncing}
                className="px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 font-semibold text-xs transition cursor-pointer"
              >
                {syncing ? 'Sincronizando...' : 'Sincronizar Pluggy Sandbox (API v2)'}
              </button>
              <button
                onClick={() => setActivePage('connections')}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs cursor-pointer"
              >
                Ver Conexões
              </button>
            </div>
          </div>
        )}

        {/* PAGE 1: DASHBOARD */}
        {activePage === 'dashboard' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-bold text-white">Resumo Financeiro & Orçamentos</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Valores calculados em centavos exatos • Gastos confirmados separados de pendentes
                </p>
              </div>

              {/* Period Selector */}
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { id: 'today', label: 'Hoje' },
                  { id: 'week', label: 'Últimos 7 dias' },
                  { id: 'month', label: 'Mês Atual' },
                  { id: 'custom', label: 'Personalizado' },
                ].map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setPeriod(p.id as any)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                      period === p.id
                        ? 'bg-teal-600 text-white'
                        : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
                <button
                  onClick={() => setNewTxModal(true)}
                  className="ml-2 px-3 py-1.5 rounded-lg bg-teal-600/20 border border-teal-500/40 text-teal-300 text-xs font-semibold hover:bg-teal-600/30 cursor-pointer flex items-center gap-1"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Nova Compra (Ex: iFood)
                </button>
              </div>
            </div>

            {period === 'custom' && (
              <div className="flex flex-wrap items-end gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Data Inicial</label>
                  <input
                    type="date"
                    value={customStart}
                    onChange={(e) => setCustomStart(e.target.value)}
                    className="px-3 py-1.5 rounded bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Data Final</label>
                  <input
                    type="date"
                    value={customEnd}
                    onChange={(e) => setCustomEnd(e.target.value)}
                    className="px-3 py-1.5 rounded bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
              </div>
            )}

            {/* KPI Strip: Hoje, Semana, Mês e Saldo Disponível de Orçamentos */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-xs text-slate-400">Gastos Hoje ({dashboard.period.today_sp})</span>
                <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                  {dashboard.summary.today_confirmed_brl}
                </div>
                <div className="mt-1 text-xs text-amber-400 tabular-nums">
                  Pendentes hoje: {dashboard.summary.today_pending_brl}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-xs text-slate-400">Gastos nos Últimos 7 Dias</span>
                <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                  {dashboard.summary.week_confirmed_brl}
                </div>
                <div className="mt-1 text-xs text-amber-400 tabular-nums">
                  Pendentes na semana: {dashboard.summary.week_pending_brl}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-xs text-slate-400">Gastos Confirmados no Mês</span>
                <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                  {dashboard.summary.month_confirmed_brl}
                </div>
                <div className="mt-1 text-xs text-amber-400 tabular-nums">
                  Pendentes no mês: {dashboard.summary.month_pending_brl}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-900 border border-teal-500/30">
                <span className="text-xs text-teal-300">Saldo Disponível nos Orçamentos</span>
                <div className="mt-1 text-2xl font-bold text-emerald-400 tabular-nums">
                  {dashboard.summary.total_budget_remaining_brl}
                </div>
                <div className="mt-1 text-xs text-slate-400 tabular-nums">
                  De {dashboard.summary.total_budget_limit_brl} planejados no mês
                </div>
              </div>
            </div>

            {/* Orçamentos por Categoria (Destaque Principal) */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-bold text-white">
                  Orçamentos Mensais por Categoria (Meta Pessoal ≠ Limite Bancário)
                </h3>
                <button
                  onClick={() => setActivePage('budgets')}
                  className="text-xs text-teal-400 hover:underline flex items-center gap-1 cursor-pointer"
                >
                  Gerenciar orçamentos e regras <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {dashboard.budgets.map((b: any) => {
                  const isExceeded = b.state === 'EXCEEDED';
                  const isWarn = b.state === 'WARNING';
                  return (
                    <div
                      key={b.id}
                      className={`p-4 rounded-xl bg-slate-900 border flex flex-col justify-between ${
                        isExceeded
                          ? 'border-red-500/60'
                          : isWarn
                          ? 'border-amber-500/50'
                          : 'border-slate-800'
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-sm text-white">{b.category_name}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                              isExceeded
                                ? 'bg-red-500/20 text-red-300'
                                : isWarn
                                ? 'bg-amber-500/20 text-amber-300'
                                : 'bg-emerald-500/15 text-emerald-300'
                            }`}
                          >
                            {isExceeded ? 'Limite Excedido' : isWarn ? 'Atenção' : 'Normal'}
                          </span>
                        </div>

                        <div className="mt-3 grid grid-cols-2 gap-2 p-3 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
                          <div>
                            <span className="text-slate-400 block">
                              {b.remaining_cents >= 0 ? 'Saldo Disponível' : 'Acima do Limite'}
                            </span>
                            <span
                              className={`text-base font-bold tabular-nums ${
                                b.remaining_cents < 0 ? 'text-red-400' : 'text-emerald-400'
                              }`}
                            >
                              {b.remaining_cents >= 0 ? b.remaining_brl : b.exceeded_brl}
                            </span>
                          </div>
                          <div className="text-right">
                            <span className="text-slate-400 block">Gasto / Orçamento</span>
                            <span className="font-semibold text-slate-200 tabular-nums">
                              {b.accounted_spent_brl} / {b.limit_brl}
                            </span>
                          </div>
                        </div>

                        {/* Progress bar */}
                        <div className="mt-3">
                          <div className="flex justify-between text-xs mb-1">
                            <span className="text-slate-400">
                              Percentual consumido ({b.include_pending ? 'c/ pendentes' : 'confirmados'})
                            </span>
                            <span className="font-bold tabular-nums">{b.percentage_used}%</span>
                          </div>
                          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${Math.min(100, Math.max(0, b.percentage_used))}%`,
                                backgroundColor: isExceeded ? '#ef4444' : isWarn ? '#f59e0b' : b.category_color,
                              }}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                        <span>Pendentes: {b.pending_spent_brl}</span>
                        <span>Projeção mês: {b.projected_spent_brl}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Evolução Diária & Distribuição por Categoria */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 p-5 rounded-xl bg-slate-900 border border-slate-800">
                <h3 className="text-sm font-bold text-white mb-1">
                  Evolução Diária de Gastos (Últimos 14 dias — America/Sao_Paulo)
                </h3>
                <p className="text-xs text-slate-400 mb-4">
                  Barras indicam despesas confirmadas e pendentes por dia
                </p>
                <div className="flex items-end gap-2 h-40 pt-4 border-b border-slate-800">
                  {(() => {
                    const maxVal = Math.max(
                      ...dashboard.daily_evolution.map((d: any) => d.confirmed_cents + d.pending_cents),
                      10000
                    );
                    return dashboard.daily_evolution.map((d: any) => {
                      const totalCents = d.confirmed_cents + d.pending_cents;
                      const hPct = Math.max(6, Math.round((totalCents / maxVal) * 100));
                      return (
                        <div key={d.date_iso} className="flex-1 flex flex-col items-center group">
                          <span className="text-[10px] text-slate-400 mb-1 opacity-0 group-hover:opacity-100">
                            R${Math.round(totalCents / 100)}
                          </span>
                          <div className="w-full max-w-[24px] bg-slate-800/60 rounded-t h-28 flex items-end">
                            <div
                              className="w-full bg-teal-500 rounded-t transition-all"
                              style={{ height: `${hPct}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-400 mt-1.5 tabular-nums">{d.label}</span>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>

              <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
                <h3 className="text-sm font-bold text-white mb-1">Maiores Gastos por Categoria</h3>
                <p className="text-xs text-slate-400 mb-4">No período selecionado</p>
                {dashboard.category_breakdown.length ? (
                  <ul className="space-y-2.5 text-xs">
                    {dashboard.category_breakdown.map((c: any) => (
                      <li key={c.name} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: c.color }} />
                          <span className="text-slate-200 font-medium">{c.name}</span>
                        </div>
                        <span className="font-bold text-white tabular-nums">{c.amount_brl}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">Nenhuma despesa registrada no período.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* PAGE 2: TRANSAÇÕES (EXTRATO PESQUISÁVEL E RECLASSIFICAÇÃO) */}
        {activePage === 'transactions' && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-bold text-white">Extrato e Detalhamento de Transações</h2>
                <p className="text-xs text-slate-400">
                  Identifique a regra aplicada, filtre por estado e corrija categorias manualmente
                </p>
              </div>
              <button
                onClick={() => setNewTxModal(true)}
                className="px-3.5 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold flex items-center gap-1.5 cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                Nova Compra / Teste
              </button>
            </div>

            {/* Filters Bar */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Buscar estabelecimento / descrição</label>
                <input
                  type="search"
                  value={txSearch}
                  onChange={(e) => setTxSearch(e.target.value)}
                  placeholder="Ex: iFood, Smart Fit, Netflix..."
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Categoria</label>
                <select
                  value={txCatFilter}
                  onChange={(e) => setTxCatFilter(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                >
                  <option value="">Todas as categorias</option>
                  {catData.categories.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Estado da Transação</label>
                <select
                  value={txStatusFilter}
                  onChange={(e) => setTxStatusFilter(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                >
                  <option value="">Todos (Confirmadas + Pendentes)</option>
                  <option value="POSTED">Confirmada (POSTED)</option>
                  <option value="PENDING">Pendente (PENDING)</option>
                  <option value="CANCELLED">Cancelada</option>
                </select>
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Natureza</label>
                <select
                  value={txTypeFilter}
                  onChange={(e) => setTxTypeFilter(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                >
                  <option value="">Todas</option>
                  <option value="EXPENSE">Despesa de Consumo</option>
                  <option value="REFUND">Estorno / Reembolso</option>
                  <option value="BILL_PAYMENT">Pagamento de Fatura (Ignorado no Orçamento)</option>
                  <option value="INCOME">Receita / Salário</option>
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 cursor-pointer py-2">
                  <input
                    type="checkbox"
                    checked={uncatOnly}
                    onChange={(e) => setUncatOnly(e.target.checked)}
                    className="w-4 h-4 accent-teal-500"
                  />
                  <span className="text-slate-200 font-medium">Apenas Não Categorizadas</span>
                </label>
              </div>
            </div>

            {/* Transactions Table */}
            <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
              <table className="w-full text-left text-xs sm:text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 text-xs">
                    <th className="p-3.5">Data (SP)</th>
                    <th className="p-3.5">Estabelecimento / Descrição</th>
                    <th className="p-3.5">Categoria & Regra Aplicada</th>
                    <th className="p-3.5">Estado / Natureza</th>
                    <th className="p-3.5 text-right">Valor</th>
                    <th className="p-3.5 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {txData.items.length ? (
                    txData.items.map((t: any) => (
                      <tr key={t.id} className="hover:bg-slate-800/40">
                        <td className="p-3.5 whitespace-nowrap tabular-nums text-slate-300">
                          {t.date_formatted}
                        </td>
                        <td className="p-3.5">
                          <div className="font-semibold text-white">
                            {t.original_description}
                            {t.installment_number && t.total_installments && (
                              <span className="ml-2 px-1.5 py-0.5 text-[10px] rounded bg-slate-800 text-teal-300">
                                Parcela {t.installment_number}/{t.total_installments}
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] text-slate-400">
                            {t.card_label} • Origem: {t.data_source}
                          </div>
                        </td>
                        <td className="p-3.5">
                          <div className="flex items-center gap-2">
                            <span
                              className="w-2.5 h-2.5 rounded-full shrink-0"
                              style={{ backgroundColor: t.category_color }}
                            />
                            <span className="font-medium text-slate-200">{t.category_name}</span>
                          </div>
                          <div className="text-[11px] text-slate-400 mt-0.5">
                            {t.applied_rule_name || `Fonte: ${t.categorization_source}`}
                          </div>
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold mr-1.5 ${
                              t.status === 'POSTED'
                                ? 'bg-emerald-500/15 text-emerald-300'
                                : t.status === 'PENDING'
                                ? 'bg-amber-500/20 text-amber-300'
                                : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {t.status === 'POSTED' ? 'Confirmada' : t.status === 'PENDING' ? 'Pendente' : t.status}
                          </span>
                          <span className="text-[11px] text-slate-400">{t.tx_type}</span>
                        </td>
                        <td className="p-3.5 text-right font-bold tabular-nums text-white whitespace-nowrap">
                          {t.amount_brl}
                        </td>
                        <td className="p-3.5 text-right whitespace-nowrap space-x-2">
                          <button
                            onClick={() => {
                              setReclassifyingTx(t);
                              setReclassCatId(t.category_id || catData.categories[0]?.id || 1);
                              setRulePatternOnReclass(t.merchant_name || t.normalized_description);
                            }}
                            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-teal-300 text-xs font-medium cursor-pointer"
                          >
                            Categorizar
                          </button>
                          <button
                            onClick={async () => {
                              await fetch(`/api/transactions/${t.id}`, { method: 'DELETE' });
                              await refreshAll();
                            }}
                            className="p-1 text-slate-500 hover:text-red-400 cursor-pointer"
                            title="Remover transação"
                          >
                            <Trash2 className="w-4 h-4 inline" />
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="p-8 text-center text-slate-400">
                        Nenhuma transação encontrada para os filtros selecionados.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* PAGE 3: ORÇAMENTOS E REGRAS DETERMINÍSTICAS */}
        {activePage === 'budgets' && (
          <div className="space-y-8">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-bold text-white">Orçamentos Mensais & Regras de Categorização</h2>
                <p className="text-xs text-slate-400">
                  Configure limites por categoria, tratamento de compras pendentes e regras automáticas por estabelecimento
                </p>
              </div>
              <button
                onClick={() => {
                  setEditingBudget(null);
                  setBudgetForm({
                    category_id: catData.categories[0]?.id || 1,
                    name: 'Novo Orçamento',
                    limit_reais: '500.00',
                    include_pending: false,
                    alert_thresholds: '50,75,90,100',
                  });
                  setBudgetModal(true);
                }}
                className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold cursor-pointer"
              >
                + Definir Orçamento
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {dashboard.budgets.map((b: any) => (
                <div key={b.id} className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex justify-between items-start">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: b.category_color }} />
                      <h3 className="font-bold text-white text-base">{b.category_name}</h3>
                    </div>
                    <p className="text-xs text-slate-400">
                      Limite: <strong className="text-white">{b.limit_brl}</strong> • Gasto: <strong className="text-white">{b.accounted_spent_brl}</strong> • Disponível: <strong className="text-emerald-400">{b.remaining_brl}</strong>
                    </p>
                    <p className="text-[11px] text-slate-500">
                      Alertas em: {b.alert_thresholds}% • Pendentes no cálculo: {b.include_pending ? 'Sim' : 'Separados'}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setEditingBudget(b);
                      setBudgetForm({
                        category_id: b.category_id,
                        name: b.name,
                        limit_reais: (b.limit_cents / 100).toFixed(2),
                        include_pending: b.include_pending,
                        alert_thresholds: b.alert_thresholds,
                      });
                      setBudgetModal(true);
                    }}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
                  >
                    Editar
                  </button>
                </div>
              ))}
            </div>

            {/* Regras de Categorização */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
              <h3 className="text-base font-bold text-white">Regras Determinísticas de Categorização</h3>
              <form onSubmit={handleCreateRule} className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Termo / Estabelecimento</label>
                  <input
                    type="text"
                    required
                    value={ruleForm.pattern}
                    onChange={(e) => setRuleForm({ ...ruleForm, pattern: e.target.value })}
                    placeholder="Ex: IFOOD, UBER, SMART FIT"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Categoria Destino</label>
                  <select
                    value={ruleForm.category_id}
                    onChange={(e) => setRuleForm({ ...ruleForm, category_id: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  >
                    {catData.categories.map((c: any) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Prioridade</label>
                  <input
                    type="number"
                    value={ruleForm.priority}
                    onChange={(e) => setRuleForm({ ...ruleForm, priority: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div className="flex items-end">
                  <button
                    type="submit"
                    className="w-full py-2 px-4 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-bold cursor-pointer"
                  >
                    Adicionar Regra
                  </button>
                </div>
              </form>

              <div className="max-h-64 overflow-y-auto border-t border-slate-800 pt-3">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="text-slate-400 border-b border-slate-800">
                      <th className="py-2">Padrão</th>
                      <th className="py-2">Categoria</th>
                      <th className="py-2">Prioridade</th>
                      <th className="py-2 text-right">Ação</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {catData.rules.map((r: any) => (
                      <tr key={r.id}>
                        <td className="py-2 font-mono text-teal-300">{r.pattern}</td>
                        <td className="py-2 text-slate-200">{r.category_name}</td>
                        <td className="py-2 text-slate-400">{r.priority}</td>
                        <td className="py-2 text-right">
                          <button
                            onClick={async () => {
                              await fetch(`/api/rules/${r.id}`, { method: 'DELETE' });
                              await refreshAll();
                            }}
                            className="text-red-400 hover:underline cursor-pointer"
                          >
                            Remover
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* PAGE 4: RELATÓRIOS AUTOMÁTICOS DIÁRIOS E SEMANAIS */}
        {activePage === 'reports' && reportsData && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-bold text-white">Relatórios Passivos (Diário & Semanal)</h2>
                <p className="text-xs text-slate-400">
                  Gerados automaticamente às {settings?.report_preferences?.daily_time || '20:00'} (America/Sao_Paulo) com controle de idempotência
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleTriggerReport('daily')}
                  className="px-3.5 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold flex items-center gap-1.5 cursor-pointer"
                >
                  <Mail className="w-4 h-4" />
                  Gerar e Enviar Relatório Diário Agora
                </button>
                <button
                  onClick={() => handleTriggerReport('weekly')}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold cursor-pointer"
                >
                  Gerar Relatório Semanal
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
                <h3 className="text-sm font-bold text-teal-400 uppercase tracking-wider mb-3">
                  Prévia Ao Vivo — Relatório Diário
                </h3>
                <pre className="whitespace-pre-wrap text-xs text-slate-200 font-sans leading-relaxed bg-slate-950 p-4 rounded-lg border border-slate-800">
                  {reportsData.daily_preview.content_markdown}
                </pre>
              </div>

              <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
                <h3 className="text-sm font-bold text-sky-400 uppercase tracking-wider mb-3">
                  Prévia Ao Vivo — Relatório Semanal
                </h3>
                <pre className="whitespace-pre-wrap text-xs text-slate-200 font-sans leading-relaxed bg-slate-950 p-4 rounded-lg border border-slate-800">
                  {reportsData.weekly_preview.content_markdown}
                </pre>
              </div>
            </div>

            {/* Histórico de Envios e Execuções */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
              <h3 className="text-base font-bold text-white mb-3">Histórico de Entregas de Notificações (E-mail / Telegram / Discord)</h3>
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="py-2">Data/Hora</th>
                    <th className="py-2">Tipo</th>
                    <th className="py-2">Canal</th>
                    <th className="py-2">Destinatário</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {reportsData.deliveries.map((d: any) => (
                    <tr key={d.id}>
                      <td className="py-2.5 text-slate-300">{d.created_at}</td>
                      <td className="py-2.5 font-medium text-white">{d.event_type}</td>
                      <td className="py-2.5 text-slate-300">{d.channel}</td>
                      <td className="py-2.5 text-slate-300">{d.recipient}</td>
                      <td className="py-2.5">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                            d.status === 'SENT'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : d.status === 'FAILED'
                              ? 'bg-red-500/20 text-red-300'
                              : 'bg-amber-500/20 text-amber-300'
                          }`}
                        >
                          {d.status}
                        </span>
                        {d.error_message && (
                          <span className="block text-[11px] text-slate-400 mt-0.5">{d.error_message}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* PAGE 5: CONEXÕES BANCÁRIAS & DIAGNÓSTICO DE VIABILIDADE PLUGGY */}
        {activePage === 'connections' && viability && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-bold text-white">Conexões Bancárias (Pluggy Open Finance)</h2>
                <p className="text-xs text-slate-400">
                  Gerencie o consentimento Open Finance, conecte o Santander ou valide via Pluggy Sandbox
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleConnectSandboxNow}
                  disabled={syncing}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-teal-300 text-xs font-bold cursor-pointer"
                >
                  {syncing ? 'Sincronizando...' : 'Conectar & Sincronizar Pluggy Sandbox (1-Clique)'}
                </button>
                <button
                  onClick={handleConnectPluggyWidget}
                  className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold cursor-pointer"
                >
                  Abrir Widget Oficial Pluggy (Santander / Outros)
                </button>
              </div>
            </div>

            {/* Diagnóstico Técnico de Viabilidade (Seção 3.1 do Prompt) */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-teal-400" />
                Diagnóstico Técnico da Conta Pluggy & Conector Santander
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-slate-400 block">Autenticação Backend (/auth)</span>
                  <span className="font-bold text-emerald-400 mt-1 block">
                    {viability.authenticated ? `Ativa (Client ID ${viability.client_id_masked})` : 'Pendente'}
                  </span>
                  <span className="text-[11px] text-slate-500 mt-1 block">
                    Chaves mantidas exclusivamente no servidor.
                  </span>
                </div>
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-slate-400 block">Conector Santander (ID 608)</span>
                  <span className="font-bold text-white mt-1 block">
                    ONLINE • Open Finance Brasil
                  </span>
                  <span className="text-[11px] text-slate-500 mt-1 block">
                    Suporta CREDIT_CARDS, TRANSACTIONS (/v2/transactions) e ACCOUNTS.
                  </span>
                </div>
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-slate-400 block">Requisito para Santander Real</span>
                  <span className="font-bold text-amber-300 mt-1 block">
                    Consentimento no App Santander
                  </span>
                  <span className="text-[11px] text-slate-500 mt-1 block">
                    Exige aprovação OAuth/QR Code pelo titular e plano Pluggy com Open Finance de produção ativo.
                  </span>
                </div>
              </div>
            </div>

            {/* Lista de Instituições Conectadas */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
              <h3 className="text-base font-bold text-white">Instituições Conectadas</h3>
              {viability.connections.length ? (
                <div className="space-y-3">
                  {viability.connections.map((c: any) => (
                    <div
                      key={c.id}
                      className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex flex-wrap items-center justify-between gap-4"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white text-sm">{c.connector_name}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              c.is_sandbox ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'
                            }`}
                          >
                            {c.is_sandbox ? 'SANDBOX DE TESTE' : 'PRODUÇÃO OPEN FINANCE'}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300">
                            Status: {c.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          Item ID: <code className="text-slate-300">{c.pluggy_item_id}</code>
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleManualSyncItem(c.pluggy_item_id)}
                          disabled={syncing}
                          className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white cursor-pointer"
                        >
                          Atualizar Dados
                        </button>
                        <button
                          onClick={() => handleDisconnectBank(c.id, c.connector_name)}
                          className="px-3 py-1.5 rounded-lg bg-red-950/60 hover:bg-red-900/60 border border-red-500/30 text-xs font-semibold text-red-300 cursor-pointer"
                        >
                          Revogar e Desconectar
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400">
                  Nenhuma instituição conectada ainda. Clique em "Conectar & Sincronizar Pluggy Sandbox (1-Clique)" acima para importar os dados reais do Sandbox da Pluggy ou abra o Widget para conectar o Santander.
                </p>
              )}
            </div>
          </div>
        )}

        {/* PAGE 6: CONFIGURAÇÕES, CANAIS DE NOTIFICAÇÃO E LGPD */}
        {activePage === 'settings' && settings && (
          <div className="space-y-6">
            <h2 className="text-xl font-bold text-white border-b border-slate-800 pb-4">
              Configurações de Relatórios, Notificações (E-mail / Telegram) e Privacidade LGPD
            </h2>

            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                await fetch('/api/settings', {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    user_name: fd.get('user_name'),
                    email_address: fd.get('email_address'),
                    email_enabled: fd.get('email_enabled') === 'on',
                    daily_time: fd.get('daily_time'),
                    telegram_enabled: fd.get('telegram_enabled') === 'on',
                    telegram_bot_token: fd.get('telegram_bot_token'),
                    telegram_chat_id: fd.get('telegram_chat_id'),
                  }),
                });
                notify('Preferências salvas com sucesso!', 'ok');
                await refreshAll();
              }}
              className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4 text-xs"
            >
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1">Nome do Titular</label>
                  <input
                    name="user_name"
                    defaultValue={settings.user_name}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">E-mail para Relatórios Diários/Semanais</label>
                  <input
                    name="email_address"
                    type="email"
                    defaultValue={settings.notification_preferences.email_address}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Horário Diário (America/Sao_Paulo)</label>
                  <input
                    name="daily_time"
                    type="time"
                    defaultValue={settings.report_preferences?.daily_time || '20:00'}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-3 border-t border-slate-800">
                <div>
                  <label className="block text-slate-400 mb-1">Telegram Bot Token (Opcional)</label>
                  <input
                    name="telegram_bot_token"
                    defaultValue={settings.notification_preferences.telegram_bot_token}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Telegram Chat ID (Opcional)</label>
                  <input
                    name="telegram_chat_id"
                    defaultValue={settings.notification_preferences.telegram_chat_id}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white font-mono"
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-6 pt-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    name="email_enabled"
                    defaultChecked={settings.notification_preferences.email_enabled}
                    className="w-4 h-4 accent-teal-500"
                  />
                  <span>Habilitar envio por E-mail (Canal Prioritário MVP)</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    name="telegram_enabled"
                    defaultChecked={settings.notification_preferences.telegram_enabled}
                    className="w-4 h-4 accent-teal-500"
                  />
                  <span>Habilitar envio por Telegram Bot</span>
                </label>
              </div>

              <button
                type="submit"
                className="px-5 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-bold cursor-pointer"
              >
                Salvar Preferências
              </button>
            </form>

            {/* Transparência LGPD */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-2 text-xs text-slate-300">
              <h3 className="text-sm font-bold text-white">Privacidade, Segurança e Conformidade LGPD</h3>
              <p>
                • <strong>Finalidade e Necessidade:</strong> Coletamos apenas metadados de contas, cartões e transações necessários para o cálculo de orçamentos e envio dos relatórios solicitados.
              </p>
              <p>
                • <strong>Sem Credenciais Bancárias:</strong> Senhas bancárias e tokens de transação jamais passam por este servidor; a autorização ocorre via Open Finance Brasil na instituição detentora da conta.
              </p>
              <p>
                • <strong>Revogação e Exclusão:</strong> Ao desconectar uma instituição na aba "Conexões Bancárias", o consentimento é revogado na Pluggy (`DELETE /items/{'{id}'}`) e todas as transações vinculadas são removidas do banco de dados local.
              </p>
            </div>
          </div>
        )}
      </main>

      {/* Modal: Registrar / Testar Compra (Ex: iFood R$ 100) */}
      {newTxModal && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-white">Registrar Compra / Testar Regra de Orçamento</h3>
              <button onClick={() => setNewTxModal(false)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleCreateTransaction} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Descrição na Fatura</label>
                <input
                  type="text"
                  required
                  value={newTxForm.description}
                  onChange={(e) => setNewTxForm({ ...newTxForm, description: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 mb-1">Valor (R$)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={newTxForm.amount_reais}
                    onChange={(e) => setNewTxForm({ ...newTxForm, amount_reais: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Estado</label>
                  <select
                    value={newTxForm.status}
                    onChange={(e) => setNewTxForm({ ...newTxForm, status: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  >
                    <option value="POSTED">Confirmada (POSTED)</option>
                    <option value="PENDING">Pendente (PENDING)</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setNewTxModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-bold cursor-pointer"
                >
                  Registrar e Recalcular Orçamento
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Reclassificar Transação Manualmente */}
      {reclassifyingTx && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-white">Corrigir Categoria: {reclassifyingTx.original_description}</h3>
              <button onClick={() => setReclassifyingTx(null)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleReclassifySubmit} className="space-y-3">
              <div>
                <label className="block text-slate-400 mb-1">Nova Categoria</label>
                <select
                  value={reclassCatId}
                  onChange={(e) => setReclassCatId(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                >
                  {catData.categories.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={createRuleOnReclass}
                  onChange={(e) => setCreateRuleOnReclass(e.target.checked)}
                  className="w-4 h-4 accent-teal-500"
                />
                <span className="text-slate-200">Criar regra automática para próximas compras deste estabelecimento</span>
              </label>
              {createRuleOnReclass && (
                <div>
                  <label className="block text-slate-400 mb-1">Padrão da Regra (CONTAINS)</label>
                  <input
                    type="text"
                    value={rulePatternOnReclass}
                    onChange={(e) => setRulePatternOnReclass(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white font-mono"
                  />
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setReclassifyingTx(null)}
                  className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-bold cursor-pointer"
                >
                  Salvar Categoria
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Criar / Editar Orçamento */}
      {budgetModal && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-white">
                {editingBudget ? `Editar Orçamento: ${editingBudget.category_name}` : 'Novo Orçamento Mensal'}
              </h3>
              <button onClick={() => setBudgetModal(false)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSaveBudget} className="space-y-3">
              {!editingBudget && (
                <div>
                  <label className="block text-slate-400 mb-1">Categoria</label>
                  <select
                    value={budgetForm.category_id}
                    onChange={(e) => setBudgetForm({ ...budgetForm, category_id: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                  >
                    {catData.categories.map((c: any) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="block text-slate-400 mb-1">Nome do Orçamento</label>
                <input
                  type="text"
                  required
                  value={budgetForm.name}
                  onChange={(e) => setBudgetForm({ ...budgetForm, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Limite Mensal (R$)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={budgetForm.limit_reais}
                  onChange={(e) => setBudgetForm({ ...budgetForm, limit_reais: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white"
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={budgetForm.include_pending}
                  onChange={(e) => setBudgetForm({ ...budgetForm, include_pending: e.target.checked })}
                  className="w-4 h-4 accent-teal-500"
                />
                <span className="text-slate-200">Incluir transações pendentes (PENDING) no consumo principal</span>
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setBudgetModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-bold cursor-pointer"
                >
                  Salvar Orçamento
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

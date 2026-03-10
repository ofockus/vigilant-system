import { useState, useEffect } from "react";
import {
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Info,
  TrendingUp,
  DollarSign,
  Activity
} from "lucide-react";

export function Suggestions({ riskPercentage, totalBalance }: any) {
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [narratives, setNarratives] = useState<any[]>([]);
  const [loadingNarratives, setLoadingNarratives] = useState(true);

  const maxRiskAmount = (totalBalance * riskPercentage) / 100;

  useEffect(() => {
    fetch("/api/binance/narratives")
      .then(res => res.json())
      .then(data => {
        setNarratives(data);
        setLoadingNarratives(false);
      })
      .catch(err => {
        console.error("Failed to fetch narratives", err);
        setLoadingNarratives(false);
      });
  }, []);

  const handleConfirm = (id: string) => {
    setConfirmed((prev) => ({ ...prev, [id]: true }));
    // In a real app, this would trigger a deep link to Binance App
    alert(
      "Abra o app da Binance e execute a operação sugerida. O Trinity Wallet não executa trades automaticamente.",
    );
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-4 flex gap-3 items-start">
        <Info className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-emerald-400 mb-1">
            Modo Leitura Ativo
          </p>
          <p className="text-xs text-emerald-500/80 leading-relaxed">
            As sugestões abaixo são baseadas no seu saldo e risco ({riskPercentage}% = R$ {maxRiskAmount.toFixed(2).replace('.', ',')}). Nenhuma
            operação será executada sem sua confirmação manual no app da
            Binance.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
          Oportunidades Seguras
        </h2>

        {/* Suggestion 1: Simple Earn */}
        <SuggestionCard
          id="earn-1"
          title="Mover USDT ocioso para Earn"
          type="Baixo Risco"
          description="Você tem 120 USDT parados na carteira Spot. Mova para o Simple Earn Flexível para render ~5% APY."
          actionText="CONFIRMAR NO APP"
          icon={<DollarSign className="w-5 h-5 text-emerald-400" />}
          isConfirmed={confirmed["earn-1"]}
          onConfirm={() => handleConfirm("earn-1")}
        />

        {/* Suggestion 2: Funding Carry */}
        <SuggestionCard
          id="funding-1"
          title="Funding Carry Seletivo"
          type="Médio Risco"
          description={`Prêmio de funding do par SOL/USDT está > 0.15%. Sugestão: Short 1x com ${riskPercentage}% da banca (R$ ${maxRiskAmount.toFixed(2).replace('.', ',')}) para capturar a taxa.`}
          actionText="VERIFICAR FUNDING"
          icon={<TrendingUp className="w-5 h-5 text-amber-400" />}
          isConfirmed={confirmed["funding-1"]}
          onConfirm={() => handleConfirm("funding-1")}
        />

        {/* Suggestion 3: Narrative Sniping */}
        {loadingNarratives ? (
          <div className="border border-zinc-800 rounded-2xl p-5 bg-zinc-900/50 animate-pulse h-40"></div>
        ) : narratives.length > 0 ? (
          <SuggestionCard
            id="narrative-1"
            title={`Narrative Sniping (${narratives[0].name})`}
            type="Alto Risco"
            description={`Volume anormal detectado na narrativa de ${narratives[0].name}. O token ${narratives[0].topCoin.symbol} subiu ${narratives[0].topCoin.change}%. Sugestão: Compra fracionada de R$ ${(maxRiskAmount * 0.5).toFixed(2).replace('.', ',')} (dentro do limite de ${riskPercentage}%).`}
            actionText="CONFIRMAR HUMANA"
            icon={<Activity className="w-5 h-5 text-rose-400" />}
            isConfirmed={confirmed["narrative-1"]}
            onConfirm={() => handleConfirm("narrative-1")}
          />
        ) : (
          <SuggestionCard
            id="narrative-1"
            title="Narrative Sniping (AI)"
            type="Alto Risco"
            description={`Volume anormal detectado em tokens de IA (FET, AGIX). Sugestão: Compra fracionada de R$ ${(maxRiskAmount * 0.5).toFixed(2).replace('.', ',')} (dentro do limite de ${riskPercentage}%).`}
            actionText="CONFIRMAR HUMANA"
            icon={<AlertTriangle className="w-5 h-5 text-rose-400" />}
            isConfirmed={confirmed["narrative-1"]}
            onConfirm={() => handleConfirm("narrative-1")}
          />
        )}
      </div>
    </div>
  );
}

function SuggestionCard({
  id,
  title,
  type,
  description,
  actionText,
  icon,
  isConfirmed,
  onConfirm,
}: any) {
  return (
    <div
      className={`border rounded-2xl p-5 transition-all duration-300 ${isConfirmed ? "bg-zinc-900/20 border-zinc-800/30 opacity-60" : "bg-zinc-900/50 border-zinc-800"}`}
    >
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-zinc-950 rounded-xl border border-zinc-800/50">
            {icon}
          </div>
          <div>
            <h3 className="font-medium text-zinc-100">{title}</h3>
            <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
              {type}
            </span>
          </div>
        </div>
        {isConfirmed && <CheckCircle2 className="w-5 h-5 text-emerald-500" />}
      </div>

      <p className="text-sm text-zinc-400 leading-relaxed mb-5">
        {description}
      </p>

      <button
        onClick={onConfirm}
        disabled={isConfirmed}
        className={`w-full py-3 px-4 rounded-xl text-xs font-bold tracking-wider uppercase transition-all flex items-center justify-center gap-2
          ${
            isConfirmed
              ? "bg-zinc-800 text-zinc-500 cursor-not-allowed"
              : "bg-zinc-100 text-zinc-950 hover:bg-white active:scale-[0.98]"
          }`}
      >
        {isConfirmed ? "Confirmado" : actionText}
        {!isConfirmed && <ArrowRight className="w-4 h-4" />}
      </button>
    </div>
  );
}

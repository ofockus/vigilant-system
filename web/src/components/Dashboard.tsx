import { useState, useEffect } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";

export function Dashboard({ riskPercentage, setRiskPercentage, totalBalance }: any) {
  const [balance, setBalance] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [isEditingRisk, setIsEditingRisk] = useState(false);
  const [tempRisk, setTempRisk] = useState(riskPercentage);

  useEffect(() => {
    // Mock data for preview if API keys aren't set
    setTimeout(() => {
      setBalance([
        { asset: "USDT", free: "320.50", locked: "0.00" },
        { asset: "BTC", free: "0.0012", locked: "0.00" },
        { asset: "BNB", free: "0.15", locked: "0.00" },
      ]);
      setLoading(false);
    }, 1000);
  }, []);

  const handleSaveRisk = () => {
    setRiskPercentage(tempRisk);
    setIsEditingRisk(false);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Total Balance Card */}
      <section>
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <RefreshCw className="w-24 h-24 text-emerald-500" />
          </div>

          <p className="text-zinc-400 text-sm font-medium uppercase tracking-wider mb-2">
            Saldo Total (Est.)
          </p>
          <div className="flex items-baseline gap-2 mb-6">
            <span className="text-4xl font-light tracking-tight">R$ 430</span>
            <span className="text-zinc-500 text-sm">,00</span>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-zinc-950/50 rounded-2xl p-4 border border-zinc-800/50">
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">
                Spot
              </p>
              <p className="font-mono text-lg">R$ 120,00</p>
            </div>
            <div className="bg-emerald-500/5 rounded-2xl p-4 border border-emerald-500/10">
              <p className="text-xs text-emerald-500/70 uppercase tracking-wider mb-1 flex items-center gap-1">
                Earn{" "}
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              </p>
              <p className="font-mono text-lg text-emerald-400">R$ 310,00</p>
            </div>
          </div>
        </div>
      </section>

      {/* Risk Management */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
            Gestão de Risco
          </h2>
          <span className="text-xs font-mono text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-full">
            Ativo
          </span>
        </div>

        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-2xl p-5">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-zinc-800/50 rounded-xl">
              <ShieldIcon />
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-medium">Proteção de Capital</p>
                {!isEditingRisk && (
                  <button 
                    onClick={() => setIsEditingRisk(true)}
                    className="text-xs text-emerald-400 hover:text-emerald-300"
                  >
                    Editar
                  </button>
                )}
              </div>
              
              {isEditingRisk ? (
                <div className="mt-3 space-y-3">
                  <div className="flex items-center gap-3">
                    <input 
                      type="range" 
                      min="1" 
                      max="20" 
                      value={tempRisk} 
                      onChange={(e) => setTempRisk(Number(e.target.value))}
                      className="flex-1 accent-emerald-500"
                    />
                    <span className="font-mono text-sm w-8 text-right">{tempRisk}%</span>
                  </div>
                  <div className="flex justify-end gap-2">
                    <button 
                      onClick={() => {
                        setTempRisk(riskPercentage);
                        setIsEditingRisk(false);
                      }}
                      className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200"
                    >
                      Cancelar
                    </button>
                    <button 
                      onClick={handleSaveRisk}
                      className="px-3 py-1.5 text-xs bg-emerald-500/20 text-emerald-400 rounded-lg hover:bg-emerald-500/30"
                    >
                      Salvar
                    </button>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-zinc-400 leading-relaxed">
                  Limite máximo de risco configurado para{" "}
                  <strong className="text-zinc-200">{riskPercentage}%</strong> (R$ {((totalBalance * riskPercentage) / 100).toFixed(2).replace('.', ',')}) por
                  operação.
                </p>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Assets List */}
      <section>
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-4">
          Ativos Spot
        </h2>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 bg-zinc-900/50 rounded-2xl animate-pulse"
              ></div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {balance.map((b, i) => (
              <div
                key={i}
                className="flex items-center justify-between p-4 bg-zinc-900/30 border border-zinc-800/50 rounded-2xl"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center font-mono text-xs text-zinc-400">
                    {b.asset.substring(0, 3)}
                  </div>
                  <div>
                    <p className="font-medium">{b.asset}</p>
                    <p className="text-xs text-zinc-500 font-mono">
                      Livre: {b.free}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm">
                    ~ R$ {(parseFloat(b.free) * 5.5).toFixed(2)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="text-zinc-400"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
    </svg>
  );
}

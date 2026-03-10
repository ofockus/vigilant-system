/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from "react";
import { Shield, Wallet, Zap, FileText, Bell, Activity, Cpu, Server, Crosshair } from "lucide-react";
import { Dashboard } from "./components/Dashboard";
import { Suggestions } from "./components/Suggestions";
import { ContentGenerator } from "./components/ContentGenerator";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [riskPercentage, setRiskPercentage] = useState(8);
  const [totalBalance, setTotalBalance] = useState(430);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 font-sans selection:bg-emerald-500/30">
      {/* Mobile Container */}
      <div className="max-w-md mx-auto min-h-screen flex flex-col relative border-x border-zinc-900 shadow-2xl bg-zinc-950">
        {/* Header */}
        <header className="sticky top-0 z-50 bg-zinc-950/80 backdrop-blur-md border-b border-zinc-900 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <h1 className="font-semibold tracking-tight text-lg leading-tight">
                Trinity Wallet
              </h1>
              <p className="text-[9px] font-mono text-emerald-500/70 uppercase tracking-widest">APEX PREDATOR NEO v666</p>
            </div>
          </div>
          <button className="relative p-2 text-zinc-400 hover:text-zinc-100 transition-colors">
            <Bell className="w-5 h-5" />
            <span className="absolute top-2 right-2 w-2 h-2 bg-emerald-500 rounded-full border-2 border-zinc-950"></span>
          </button>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 overflow-y-auto pb-24 px-6 pt-6">
          {activeTab === "dashboard" && (
            <Dashboard
              riskPercentage={riskPercentage}
              setRiskPercentage={setRiskPercentage}
              totalBalance={totalBalance}
            />
          )}
          {activeTab === "suggestions" && (
            <Suggestions
              riskPercentage={riskPercentage}
              totalBalance={totalBalance}
            />
          )}
          {activeTab === "content" && <ContentGenerator />}
          {activeTab === "apex" && <ApexDashboard />}
        </main>

        {/* Bottom Navigation */}
        <nav className="absolute bottom-0 w-full bg-zinc-950/90 backdrop-blur-xl border-t border-zinc-900 pb-6">
          <div className="flex items-center justify-around p-4">
            <NavItem
              icon={<Wallet />}
              label="Carteira"
              isActive={activeTab === "dashboard"}
              onClick={() => setActiveTab("dashboard")}
            />
            <NavItem
              icon={<Zap />}
              label="Ações"
              isActive={activeTab === "suggestions"}
              onClick={() => setActiveTab("suggestions")}
            />
            <NavItem
              icon={<Crosshair />}
              label="APEX"
              isActive={activeTab === "apex"}
              onClick={() => setActiveTab("apex")}
            />
            <NavItem
              icon={<FileText />}
              label="Concurso"
              isActive={activeTab === "content"}
              onClick={() => setActiveTab("content")}
            />
          </div>
        </nav>
      </div>
    </div>
  );
}

function ApexDashboard() {
  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 flex gap-3 items-start">
        <Activity className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-red-400 mb-1">APEX PREDATOR NEO v666</p>
          <p className="text-xs text-red-500/80 leading-relaxed">
            Sistema autônomo HFT. Monitorando anomalias de volume e liquidity sweeps em tempo real.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Cpu className="w-4 h-4 text-emerald-400" />
            <span className="text-xs font-mono text-zinc-400">LATÊNCIA</span>
          </div>
          <p className="text-xl font-mono text-zinc-100">39.7<span className="text-sm text-zinc-500">ms</span></p>
        </div>
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server className="w-4 h-4 text-amber-400" />
            <span className="text-xs font-mono text-zinc-400">NODES</span>
          </div>
          <p className="text-xl font-mono text-zinc-100">8<span className="text-sm text-zinc-500">/8</span></p>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Módulos Ativos</h3>
        
        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-xl p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-200">ConfluenceGodMode</p>
            <p className="text-[10px] text-zinc-500 font-mono">8 Filtros Letais + ML Sweep</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        </div>

        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-xl p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-200">PredatorShadow</p>
            <p className="text-[10px] text-zinc-500 font-mono">Ghost Order Counter-Attacks</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        </div>

        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-xl p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-200">AdversarialShield</p>
            <p className="text-[10px] text-zinc-500 font-mono">Jitter + Rate-Limit Evasion</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        </div>

        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-xl p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-200">ApexBacktester</p>
            <p className="text-[10px] text-zinc-500 font-mono">Tick-Level Simulation</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        </div>

        <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-xl p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-200">RobinHoodRisk</p>
            <p className="text-[10px] text-zinc-500 font-mono">4% Drawdown Kill Switch</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        </div>
      </div>
    </div>
  );
}

function NavItem({
  icon,
  label,
  isActive,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-1.5 transition-colors ${isActive ? "text-emerald-400" : "text-zinc-500 hover:text-zinc-300"}`}
    >
      <div
        className={`p-1.5 rounded-xl ${isActive ? "bg-emerald-500/10" : "bg-transparent"}`}
      >
        {icon}
      </div>
      <span className="text-[10px] font-medium uppercase tracking-wider">
        {label}
      </span>
    </button>
  );
}

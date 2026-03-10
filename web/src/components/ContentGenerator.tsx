import { useState } from "react";
import {
  Copy,
  CheckCircle2,
  Sparkles,
  Video,
  Twitter,
  FileText,
} from "lucide-react";

export function ContentGenerator() {
  const [copied, setCopied] = useState<string | null>(null);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="bg-gradient-to-br from-indigo-500/10 to-purple-500/10 border border-indigo-500/20 rounded-2xl p-5 relative overflow-hidden">
        <div className="absolute top-0 right-0 p-4 opacity-20">
          <Sparkles className="w-24 h-24 text-indigo-400" />
        </div>
        <h2 className="text-lg font-semibold text-indigo-300 mb-2">
          Concurso OpenClaw
        </h2>
        <p className="text-sm text-indigo-200/70 leading-relaxed max-w-[85%]">
          Gere conteúdo automaticamente para participar do concurso da Binance
          com o projeto Trinity Wallet.
        </p>
      </div>

      <div className="space-y-6">
        {/* Pitch */}
        <ContentBlock
          id="pitch"
          title="Proposta Curta (Pitch)"
          icon={<FileText className="w-5 h-5 text-zinc-400" />}
          content="Trinity Wallet: Um assistente mobile minimalista para bancas pequenas na Binance. Foco em proteção de capital (max 8% risco), monitoramento real-time e sugestões seguras (Earn, Funding Carry) sem execução automática. O usuário no controle total."
          copied={copied}
          onCopy={handleCopy}
        />

        {/* Script */}
        <ContentBlock
          id="script"
          title="Roteiro Demo (60s)"
          icon={<Video className="w-5 h-5 text-zinc-400" />}
          content={`[0:00] Tela inicial: Mostra saldo R$430 e limite de risco 8% ativado.\n[0:15] "Banca pequena? O Trinity Wallet protege seu capital."\n[0:30] Aba Ações: Mostra sugestão de mover USDT pro Earn.\n[0:45] "Sem trade automático. Você aprova, a Binance executa."\n[0:55] "Segurança e simplicidade. Vote no Trinity Wallet!"`}
          copied={copied}
          onCopy={handleCopy}
        />

        {/* Social Post */}
        <ContentBlock
          id="social"
          title="Post Square/X"
          icon={<Twitter className="w-5 h-5 text-zinc-400" />}
          content="Construindo o Trinity Wallet pro concurso OpenClaw da @Binance! 🚀 Um app focado em proteger bancas pequenas com gestão de risco rígida (max 8%) e sugestões de Earn/Funding seguras. Tudo em modo leitura, você no controle. #BinanceBuild #OpenClaw #Crypto"
          copied={copied}
          onCopy={handleCopy}
        />
      </div>
    </div>
  );
}

function ContentBlock({ id, title, icon, content, copied, onCopy }: any) {
  return (
    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-zinc-950 rounded-xl border border-zinc-800/50">
            {icon}
          </div>
          <h3 className="font-medium text-zinc-200">{title}</h3>
        </div>
        <button
          onClick={() => onCopy(content, id)}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors text-zinc-400 hover:text-zinc-100"
        >
          {copied === id ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          ) : (
            <Copy className="w-4 h-4" />
          )}
        </button>
      </div>
      <div className="bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/30">
        <p className="text-sm text-zinc-400 leading-relaxed font-mono whitespace-pre-wrap">
          {content}
        </p>
      </div>
    </div>
  );
}

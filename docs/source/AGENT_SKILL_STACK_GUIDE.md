# OpenClaw Agent Skill Stack Guide (Security-First)

OpenClaw can be treated as an intelligent runtime container; your skill stack determines how capable (and how risky) your agent becomes.

## Core principles

1. **Safety first, always**
   - Treat skills/CLIs as early-stage software with unknown vulnerabilities.
   - Test new skills on isolated machines or cloud sandboxes.
   - Never start with large-fund transactions.
2. **Rational expectations**
   - Agents are not magic.
   - Performance depends on skill selection, orchestration design, and continuous feedback loops.
3. **Progressive hardening**
   - Start read-only, then move to low-risk writes, then to limited execution.
   - Keep least privilege in credentials and wallet permissions.

## Baseline capability stack (universal)

Before Web3 workflows, equip the agent with:
- network access + resilient web search
- retrieval + citation discipline
- self-checking (preflight, dry-runs, policy checks)
- reflection/evolution loop (postmortem + prompts/memory updates)

## Recommended skill categories

### 1) Security gate (install first)
- Skill Vetter (security review for third-party skills)
- AgentGuard / MistTrack-style risk layers for operation tracking and AML/risk checks

### 2) Search and intelligence
- x-research and multi-engine search aggregators
- Brave / Tavily style web + news retrieval

### 3) Execution and automation
- Agent Reach / Apify-style operational automation
- Exchange and wallet skill hubs (Binance / OKX / Coinbase / Bitget / BNB Chain)

### 4) Strategy and analytics
- Dune / Nansen / CoinAnk data pipelines
- Earnings/fundamental analysis stacks for traditional markets

### 5) Messaging and monitoring
- News and social MCP/skills for continuous monitoring + alerting

## Minimal secure rollout playbook

1. **Pre-install review**
   - Inspect requested permissions, external calls, and command execution scope.
2. **Sandbox validation**
   - Run in isolated environment and record all outbound network targets.
3. **Policy simulation**
   - Enforce read-only first; verify no destructive writes happen.
4. **Limited production**
   - Apply strict budgets, per-action caps, and circuit breakers.
5. **Continuous audit**
   - Keep operation logs, skill provenance, and rollback procedures.

## Suggested OpenClaw stack order

1. Security vetting skill
2. Search/research skill(s)
3. Data analytics skill(s)
4. Exchange/wallet execution skill(s)
5. Monitoring and alerting skill(s)
6. Self-improvement/reflection skill

## Safety checklist (must pass)

- [ ] No unrestricted shell/file operations granted to untrusted skills
- [ ] Wallet permissions are scoped and revocable
- [ ] Testnet/sandbox mode enabled by default
- [ ] Position sizing and loss limits are hard-coded
- [ ] Human confirmation required for high-risk operations
- [ ] Incident response and key rotation plan documented

## References (from the requested ecosystem list)

- OpenClaw Skill Vetter: https://github.com/openclaw/skills/blob/main/skills/spclaudehome/skill-vetter/SKILL.md
- x-research-skill: https://github.com/rohunvora/x-research-skill
- Multi Search Engine: https://github.com/openclaw/skills/blob/main/skills/gpyangyoujun/multi-search-engine/SKILL.md
- Brave search skills: https://github.com/brave/brave-search-skills
- Tavily skills: https://github.com/tavily-ai/skills
- Binance Skills Hub: https://developers.binance.com/cn/skills
- MistTrack skills: https://github.com/slowmist/misttrack-skills
- AgentGuard: https://github.com/GoPlusSecurity/agentguard

> DYOR. Start small. Keep security controls stronger than automation speed.

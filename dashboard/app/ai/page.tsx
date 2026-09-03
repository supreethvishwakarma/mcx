"use client";

import { useEffect, useState, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import { fetchJSON, type RLStatus, type ModelsStatus } from "@/lib/api";
import { RefreshCw } from "lucide-react";

export default function AIPage() {
  const [rl, setRl] = useState<RLStatus>({});
  const [models, setModels] = useState<ModelsStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rlData, modelsData] = await Promise.all([
        fetchJSON<RLStatus>("/api/rl/status").catch(() => ({})),
        fetchJSON<ModelsStatus>("/api/models/status").catch(() => null),
      ]);
      setRl(rlData);
      setModels(modelsData);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 p-5 overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-sm font-bold uppercase tracking-wider" style={{ color: '#00e87b' }}>AI Models</h1>
            <p className="text-[10px] mt-0.5" style={{ color: '#3d4450' }}>ML MODELS, RL AGENTS &amp; TRAINING STATUS</p>
          </div>
          <button onClick={load} className="t-btn flex items-center gap-1.5">
            <RefreshCw className="w-3 h-3" /> REFRESH
          </button>
        </div>

        {!loading && models && !models.macro.loaded && !models.micro.loaded && models.strategy_models.count === 0
          && !rl.tabular && !rl.dqn && (
          <div className="t-panel p-4 mb-4" style={{ borderColor: '#e8c300' }}>
            <p className="text-[11px]" style={{ color: '#e8c300' }}>
              ⚠ NO MODELS TRAINED YET. This is expected until real {models.primary_underlying} market data
              exists — this project deliberately never trains on synthetic data (see CLAUDE.md). Trade
              suggestions currently fall back to a neutral 0.5 ML probability.
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-[1px] mb-4">
          {/* Tabular RL agent */}
          <div className="t-panel p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-[12px] font-bold uppercase tracking-wider" style={{ color: '#4da6ff' }}>Tabular Q-Learning</h3>
                <p className="text-[10px] mt-0.5" style={{ color: '#3d4450' }}>models/saved/rl_exit_agent.pkl</p>
              </div>
              <span className="w-[6px] h-[6px]" style={{ background: rl.tabular ? '#00e87b' : '#ff3e3e' }} />
            </div>
            {rl.tabular ? (
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
                {[
                  ["States",    rl.tabular.states?.toLocaleString() ?? "--"],
                  ["Episodes",  rl.tabular.episodes?.toLocaleString() ?? "--"],
                  ["Actions",   "HOLD / EXIT / TIGHTEN"],
                  ["Type",      "Tabular Q-Table"],
                ].map(([k, v]) => (
                  <div key={String(k)}>
                    <span style={{ color: '#5a6270' }}>{k}</span>
                    <p className="font-semibold" style={{ color: '#c8cdd5' }}>{v}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px]" style={{ color: '#3d4450' }}>
                NOT TRAINED — <code style={{ color: '#4da6ff' }}>python scripts/train_rl_exit.py --epochs 10</code>
                <br />Needs real closed-trade journeys first; none exist yet for this MCX fork.
              </p>
            )}
          </div>

          {/* DQN agent */}
          <div className="t-panel p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-[12px] font-bold uppercase tracking-wider" style={{ color: '#b388ff' }}>DQN Agent</h3>
                <p className="text-[10px] mt-0.5" style={{ color: '#3d4450' }}>models/saved/dqn_exit_agent.pt</p>
              </div>
              <span className="w-[6px] h-[6px]" style={{ background: rl.dqn ? '#00e87b' : '#ff3e3e' }} />
            </div>
            {rl.dqn ? (
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
                {[
                  ["Episodes",        rl.dqn.episodes?.toLocaleString() ?? "--"],
                  ["Training Steps",  rl.dqn.training_steps?.toLocaleString() ?? "--"],
                  ["Epsilon",         rl.dqn.epsilon?.toFixed(4) ?? "--"],
                  ["Parameters",      rl.dqn.params?.toLocaleString() ?? "--"],
                ].map(([k, v]) => (
                  <div key={String(k)}>
                    <span style={{ color: '#5a6270' }}>{k}</span>
                    <p className="font-semibold" style={{ color: '#c8cdd5' }}>{v}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px]" style={{ color: '#3d4450' }}>
                NOT TRAINED — <code style={{ color: '#4da6ff' }}>python scripts/train_dqn_exit.py --epochs 10</code>
                <br />Needs real closed-trade journeys first; none exist yet for this MCX fork.
              </p>
            )}
          </div>
        </div>

        {/* System models grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-[1px] mb-4">
          <div className="t-panel p-4">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-[12px] font-bold uppercase tracking-wider" style={{ color: '#4da6ff' }}>Macro ML Model</h3>
              <span className="w-[6px] h-[6px]" style={{ background: models?.macro.loaded ? '#00e87b' : '#ff3e3e' }} />
            </div>
            <p className="text-[10px] mb-2" style={{ color: '#3d4450' }}>models/saved/macro_model.pkl</p>
            {models?.macro.loaded ? (
              <div className="space-y-0.5 text-[11px]" style={{ color: '#c8cdd5' }}>
                <p>{models.macro.feature_count} features</p>
                <p style={{ color: '#5a6270' }}>Trained: {models.macro.file.trained_at?.slice(0, 19).replace('T', ' ')}</p>
              </div>
            ) : (
              <p className="text-[11px]" style={{ color: '#3d4450' }}>
                NOT TRAINED — <code style={{ color: '#4da6ff' }}>python scripts/incremental_train.py</code> once real {models?.primary_underlying ?? "underlying"} candle history exists.
              </p>
            )}
          </div>

          <div className="t-panel p-4">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-[12px] font-bold uppercase tracking-wider" style={{ color: '#e8c300' }}>Strategy Models</h3>
              <span className="w-[6px] h-[6px]" style={{ background: (models?.strategy_models.count ?? 0) > 0 ? '#00e87b' : '#ff3e3e' }} />
            </div>
            <p className="text-[10px] mb-2" style={{ color: '#3d4450' }}>models/saved/strategy/*.pkl</p>
            {models && models.strategy_models.count > 0 ? (
              <div className="space-y-0.5 text-[11px]" style={{ color: '#c8cdd5' }}>
                {models.strategy_models.loaded.map(s => <p key={s}>{s}</p>)}
              </div>
            ) : (
              <p className="text-[11px]" style={{ color: '#3d4450' }}>
                NOT TRAINED — <code style={{ color: '#4da6ff' }}>python scripts/train_outcome_models.py</code> once real paper/live trades exist.
              </p>
            )}
          </div>

          <div className="t-panel p-4">
            <h3 className="text-[12px] font-bold uppercase tracking-wider mb-1" style={{ color: '#00e87b' }}>Vol Surface</h3>
            <p className="text-[10px] mb-2" style={{ color: '#3d4450' }}>strategy/vol_surface.py</p>
            <p className="text-[11px]" style={{ color: '#c8cdd5' }}>
              Deterministic IV-based strike-selection formula (not a trained model —
              always active once option-chain IV data is flowing).
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

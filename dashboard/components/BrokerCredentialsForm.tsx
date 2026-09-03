"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getBrokerStatus,
  saveBrokerCredentials,
  connectBroker,
  loginBrokerTotp,
  type BrokerStatus,
} from "@/lib/api";

const fieldStyle: React.CSSProperties = {
  background: "#111318",
  border: "1px solid #252a33",
  color: "#c8cdd5",
};

function Field({
  label, value, onChange, placeholder, type = "text", hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="block text-[10px] font-bold uppercase tracking-wider mb-1" style={{ color: "#5a6270" }}>
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full px-2.5 py-1.5 text-[11px] outline-none focus:border-[#00e87b]"
        style={fieldStyle}
      />
      {hint && <span className="block text-[9px] mt-1" style={{ color: "#3d4450" }}>{hint}</span>}
    </label>
  );
}

export default function BrokerCredentialsForm() {
  const [status, setStatus] = useState<BrokerStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [clientId, setClientId] = useState("");
  const [password, setPassword] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const refreshStatus = useCallback(async () => {
    const s = await getBrokerStatus().catch(() => null);
    if (s) setStatus(s);
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  const handleSave = async () => {
    if (!apiKey || !clientId || !password) {
      setMsg({ type: "err", text: "API KEY, CLIENT ID AND PASSWORD ARE REQUIRED" });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await saveBrokerCredentials({
        api_key: apiKey, client_id: clientId, password, totp_secret: totpSecret || undefined,
      });
      setMsg({ type: res.ok ? "ok" : "err", text: res.message.toUpperCase() });
      // Clear sensitive fields from memory once saved server-side
      if (res.ok) {
        setPassword("");
        setTotpSecret("");
      }
      await refreshStatus();
    } catch {
      setMsg({ type: "err", text: "FAILED TO SAVE CREDENTIALS" });
    } finally {
      setSaving(false);
    }
  };

  const handleConnect = async () => {
    setConnecting(true);
    setMsg(null);
    try {
      const res = totpCode
        ? await loginBrokerTotp(totpCode)
        : await connectBroker();
      const authenticated = "authenticated" in res ? res.authenticated : res.connected;
      setMsg({
        type: authenticated ? "ok" : "err",
        text: authenticated ? "CONNECTED TO ANGEL ONE" : "AUTHENTICATION FAILED — CHECK CREDENTIALS/TOTP",
      });
      setTotpCode("");
      await refreshStatus();
    } catch {
      setMsg({ type: "err", text: "CONNECTION REQUEST FAILED" });
    } finally {
      setConnecting(false);
    }
  };

  const isAngelOne = status?.broker === "Angel One";

  return (
    <div className="t-panel p-5 mb-4">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-[12px] font-bold uppercase tracking-wider" style={{ color: "#c8cdd5" }}>
          Angel One Connection
        </h2>
        {status && (
          <span
            className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5"
            style={{
              color: status.connected ? "#00e87b" : "#5a6270",
              border: `1px solid ${status.connected ? "#00e87b" : "#252a33"}`,
            }}
          >
            {status.broker} · {status.connected ? "CONNECTED" : "DISCONNECTED"}
          </span>
        )}
      </div>
      <p className="text-[10px] mb-4" style={{ color: "#5a6270" }}>
        Enter your Angel One SmartAPI credentials. Get an API key at{" "}
        <span style={{ color: "#4da6ff" }}>smartapi.angelbroking.com</span>. Credentials are sent
        straight to the local Flask backend and never leave this server.
      </p>

      {!isAngelOne && status && (
        <p className="text-[10px] mb-4 px-2 py-1.5" style={{ color: "#e8c300", border: "1px solid #3d3410" }}>
          ⚠ Server is running in {status.mode.toUpperCase()} mode. Set TRADE_MODE=angelone and restart
          the backend to trade live through Angel One.
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <Field label="API Key" value={apiKey} onChange={setApiKey} placeholder="Your SmartAPI key" />
        <Field label="Client ID" value={clientId} onChange={setClientId} placeholder="e.g. A123456" />
        <Field
          label="Password / PIN"
          value={password}
          onChange={setPassword}
          placeholder="Trading password or PIN"
          type="password"
        />
        <Field
          label="TOTP Secret (optional)"
          value={totpSecret}
          onChange={setTotpSecret}
          placeholder="Base32 2FA secret"
          type="password"
          hint="Stored to auto-generate codes. Leave blank and enter a one-off code below instead."
        />
      </div>

      <div className="flex items-end gap-3 flex-wrap">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider transition-all disabled:opacity-50"
          style={{ background: "#00e87b", color: "#000" }}
        >
          {saving ? "SAVING…" : "SAVE CREDENTIALS"}
        </button>

        <div className="flex items-end gap-2">
          <Field
            label="One-off TOTP code"
            value={totpCode}
            onChange={setTotpCode}
            placeholder="123456"
          />
          <button
            onClick={handleConnect}
            disabled={connecting}
            className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider transition-all disabled:opacity-50"
            style={{ background: "#181c24", border: "1px solid #4da6ff", color: "#4da6ff" }}
          >
            {connecting ? "CONNECTING…" : "CONNECT"}
          </button>
        </div>
      </div>

      {msg && (
        <p className="text-[10px] mt-3" style={{ color: msg.type === "ok" ? "#00e87b" : "#ff3e3e" }}>
          {msg.text}
        </p>
      )}
    </div>
  );
}

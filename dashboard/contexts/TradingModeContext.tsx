"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export type TradingMode = "test" | "live";

interface TradingModeContextValue {
  mode: TradingMode;
  setMode: (mode: TradingMode) => void;
  dialogError: string | null;
  setDialogError: (msg: string | null) => void;
  showDialog: boolean;
  setShowDialog: (v: boolean) => void;
}

const TradingModeContext = createContext<TradingModeContextValue | null>(null);

export function TradingModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeInternal] = useState<TradingMode>("test");
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [showDialog, setShowDialog] = useState(false);

  const setMode = useCallback((newMode: TradingMode) => {
    if (newMode === "live") {
      // Check for Angel One keys
      const apiKey = process.env.NEXT_PUBLIC_ANGEL_ONE_API_KEY;
      const apiSecret = process.env.NEXT_PUBLIC_ANGEL_ONE_API_SECRET;
      if (!apiKey || !apiSecret) {
        setDialogError("ANGEL ONE API KEYS NOT CONFIGURED\n\nSet NEXT_PUBLIC_ANGEL_ONE_API_KEY and NEXT_PUBLIC_ANGEL_ONE_API_SECRET in your .env.local file to enable live trading.");
        setShowDialog(true);
        return;
      }
    }
    setModeInternal(newMode);
  }, []);

  return (
    <TradingModeContext.Provider value={{ mode, setMode, dialogError, setDialogError, showDialog, setShowDialog }}>
      {children}
    </TradingModeContext.Provider>
  );
}

export function useTradingMode() {
  const ctx = useContext(TradingModeContext);
  if (!ctx) throw new Error("useTradingMode must be used within TradingModeProvider");
  return ctx;
}

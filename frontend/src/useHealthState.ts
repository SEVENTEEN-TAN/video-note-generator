import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHealthState } from "./api";
import type { HealthState } from "./types";

type HealthController = {
  health: HealthState | null;
  refreshHealth: () => Promise<void>;
};

const STARTUP_RETRY_DELAYS = [2000, 5000];

export function useHealthState(): HealthController {
  const [health, setHealth] = useState<HealthState | null>(null);
  const mountedRef = useRef(true);
  const requestEpochRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);

  const refreshHealth = useCallback(async () => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    try {
      const nextHealth = await fetchHealthState(controller.signal);
      if (mountedRef.current && requestEpochRef.current === requestEpoch) {
        setHealth(nextHealth);
      }
    } catch {
      if (!controller.signal.aborted && mountedRef.current && requestEpochRef.current === requestEpoch) {
        setHealth(null);
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    let stopped = false;
    let retryTimer: number | undefined;

    const runAttempt = async (attemptIndex: number) => {
      await refreshHealth();
      if (stopped || attemptIndex >= STARTUP_RETRY_DELAYS.length) {
        return;
      }
      retryTimer = window.setTimeout(
        () => void runAttempt(attemptIndex + 1),
        STARTUP_RETRY_DELAYS[attemptIndex]
      );
    };

    void runAttempt(0);
    return () => {
      stopped = true;
      mountedRef.current = false;
      requestEpochRef.current += 1;
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [refreshHealth]);

  return { health, refreshHealth };
}

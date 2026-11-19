import { useEffect, useRef, useState } from "react";
import { opinionAPI } from "@/lib/api/public-opinion";
import { delay } from "@/lib/api/delay";
import type { PlatformSession } from "@/types/public-opinion";

export type SessionAction = "check" | "login" | "confirm" | "cancel";

export function usePlatformSession(platformId: string | undefined, enabled: boolean) {
  const [bound, setBound] = useState<{ platformId: string; value?: PlatformSession; error?: string }>();
  const [attempt, setAttempt] = useState(0);
  const [acting, setActing] = useState(false);
  const current = useRef(platformId);
  current.current = enabled ? platformId : undefined;
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setActing(false);
    if (!enabled || !platformId) return;
    const controller = new AbortController();
    const path = `sessions/${encodeURIComponent(platformId)}`;
    setBound({ platformId });
    async function read() {
      try {
        let value = await opinionAPI<PlatformSession>(path, { signal: controller.signal });
        let attemptedCheck = false;
        for (;;) {
          if (controller.signal.aborted) return;
          // Only headless checks; never open a login window just because selection changed.
          if (!attemptedCheck && value.configured && value.status === "unverified" && value.remote_verification_supported) {
            attemptedCheck = true;
            value = await opinionAPI<PlatformSession>(`${path}/check`, { method: "POST", signal: controller.signal });
          }
          setBound({ platformId: platformId!, value });
          if (!["checking", "logging_in", "verified"].includes(value.status)) return;
          if (value.status === "verified") attemptedCheck = false;
          await delay(value.status === "verified" ? 30000 : 1200, controller.signal);
          value = await opinionAPI<PlatformSession>(path, { signal: controller.signal });
        }
      } catch (error) {
        if (!controller.signal.aborted) setBound({ platformId: platformId!, error: error instanceof Error ? error.message : "读取平台登录状态失败" });
      }
    }
    void read();
    return () => controller.abort();
  }, [platformId, enabled, attempt]);

  async function act(action: SessionAction) {
    if (!enabled || !platformId || acting) return;
    const ticket = generation.current;
    const path = `sessions/${encodeURIComponent(platformId)}`;
    setActing(true);
    try {
      const value = await opinionAPI<PlatformSession>(action === "cancel" ? path : `${path}/${action}`, {
        method: action === "cancel" ? "DELETE" : "POST", signal: AbortSignal.timeout(15000),
      });
      if (current.current !== platformId || ticket !== generation.current) return;
      setBound({ platformId, value });
      setAttempt(value => value + 1);
    } catch (error) {
      if (current.current === platformId && ticket === generation.current) setBound({ platformId, error: error instanceof Error ? error.message : "平台登录操作失败" });
    } finally { if (current.current === platformId && ticket === generation.current) setActing(false); }
  }
  const selected = enabled && bound?.platformId === platformId ? bound : undefined;
  return { state: selected?.value, error: selected?.error, loading: enabled && !!platformId && !selected?.value && !selected?.error,
    acting, ready: !!selected?.value?.collector_ready && !selected.error,
    act, reload: () => setAttempt(value => value + 1) };
}

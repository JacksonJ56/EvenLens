import { CheckCircle2, Loader2, LogIn, RefreshCw, X } from "lucide-react";
import type { usePlatformSession } from "@/hooks/use-platform-session";
import styles from "./platform-session-notice.module.css";

const labels = { not_logged_in: "尚未登录", unverified: "会话待验证", checking: "正在验证", logging_in: "等待本人登录", verified: "会话已验证", expired: "登录已失效", unavailable: "环境未就绪", error: "暂时无法确认", cancelled: "已取消" };
export function PlatformSessionNotice({ name, session }: { name: string; session: ReturnType<typeof usePlatformSession> }) {
  const { state, error, loading, acting, act, reload } = session;
  const working = state?.status === "checking" || state?.status === "logging_in";
  return <section className={styles.notice} aria-label={`${name}登录状态`} data-state={state?.status}>
    <div className={styles.heading}>
      {loading || working ? <Loader2 size={15} className={styles.spinner} aria-hidden="true" /> : state?.session_verified ? <CheckCircle2 size={15} aria-hidden="true" /> : <LogIn size={15} aria-hidden="true" />}
      <strong>{name} · {loading ? "读取登录状态…" : error ? "状态读取失败" : state ? labels[state.status] : "尚未检查"}</strong>
    </div>
    <p role={error ? "alert" : "status"}>{error ?? state?.message ?? "正在读取平台采集会话状态。"}</p>
    {state?.status === "logging_in" && <p>请在弹出的本机浏览器中扫码或登录，平台要求的验证由你本人完成。此步骤不会采集评论或调用 AI。</p>}
    <div className={styles.actions}>
      {error ? <button type="button" className="outline-button" onClick={reload}><RefreshCw size={13} />重新读取</button> : <>
        {state && !working && state.login_available && <button type="button" className="outline-button" disabled={acting} onClick={() => void act("login")}><LogIn size={13} />{state.configured ? "重新登录" : `登录${name}`}</button>}
        {state && !working && state.configured && state.runtime_ready && <button type="button" className="outline-button" disabled={acting} onClick={() => void act("check")}><RefreshCw size={13} />重新检查</button>}
        {state?.status === "logging_in" && <button type="button" className="outline-button" disabled={acting} onClick={() => void act("confirm")}><CheckCircle2 size={13} />完成登录并验证</button>}
        {working && <button type="button" className="outline-button" disabled={acting} onClick={() => void act("cancel")}><X size={13} />取消{state?.status === "checking" ? "验证" : "登录"}</button>}
      </>}
    </div>
    {state?.checked_at && <small>最近检查：{new Date(state.checked_at).toLocaleString("zh-CN")} · 验证结果短期缓存，执行时再次校验</small>}
  </section>;
}

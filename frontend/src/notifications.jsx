// Notifications bell for the connected app's top bar (every role). Polls every 30 s;
// a click marks the notification read and opens what it links to.
import React, { useEffect, useRef, useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { when } from "./telemetry";
import { t, tn } from "./offersText";
import { OfferNotice, usePoller } from "./offersShared";

export function NotificationBell({ api, userId, onError, onOpen, nudge = 0 }) {
  const list = usePoller((signal) => api.notifications(false, signal), {
    key: `notifications:${userId}`,
    interval: 30000,
    focus: true,
    nudge,
    onError,
  });
  const [override, setOverride] = useState(null); // result of a mark-read call
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  // A newer poll result replaces the mark-read response.
  useEffect(() => setOverride(null), [list.data]);
  const data = override || list.data;
  const unread = data?.unread_count || 0;

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector("button")?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (event) => {
      if (
        !panelRef.current?.contains(event.target) &&
        !buttonRef.current?.contains(event.target)
      )
        setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  async function choose(item) {
    setError(null);
    setOpen(false);
    if (!item.read_at) {
      try {
        setOverride(await api.markNotificationRead(item.notification_id));
      } catch (failure) {
        if (!onError(failure)) setError(failure);
      }
    }
    onOpen(item.link);
  }
  async function markAll() {
    setError(null);
    try {
      setOverride(await api.markAllNotificationsRead());
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    }
  }

  return (
    <div className="offer-bell">
      <button
        ref={buttonRef}
        className="icon-btn offer-bell-button"
        aria-label={unread ? tn("bell.label.unread", unread) : t("bell.label")}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls="offer-bell-panel"
        onClick={() => {
          setOpen(!open);
          if (!open) list.refresh();
        }}
      >
        <Bell size={18} />
        {unread > 0 && (
          <span className="offer-bell-badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          ref={panelRef}
          id="offer-bell-panel"
          className="offer-bell-panel"
          role="region"
          aria-label={t("bell.title")}
        >
          <div className="offer-bell-head">
            <b>{t("bell.title")}</b>
            <button className="text-btn" onClick={markAll} disabled={!unread}>
              <CheckCheck size={15} /> {t("bell.markAll")}
            </button>
          </div>
          <OfferNotice error={error || list.error} text={list.error && !error ? t("bell.error") : undefined} />
          {!data && !list.error && <p className="offer-bell-empty">{t("common.loading")}</p>}
          {data && !data.notifications.length && (
            <p className="offer-bell-empty">{t("bell.empty")}</p>
          )}
          {data?.notifications.length > 0 && (
            <ul>
              {data.notifications.map((item) => (
                <li key={item.notification_id}>
                  <button
                    className={`offer-bell-item ${item.read_at ? "" : "unread"}`}
                    onClick={() => choose(item)}
                  >
                    <span className="offer-bell-title">
                      {!item.read_at && <span className="offer-bell-dot" aria-hidden="true" />}
                      <b>{item.title}</b>
                      {!item.read_at && <span className="visually-hidden">{t("bell.unread")}</span>}
                    </span>
                    <span className="offer-bell-body">{item.body}</span>
                    <small>{when(item.created_at)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

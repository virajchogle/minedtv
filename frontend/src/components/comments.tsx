"use client";

/**
 * Comments under a clip: newest first, one level of replies (a reply to a reply attaches to the
 * top-level comment, like the backend). Posting needs a user; deleting is for the comment's
 * author or the clip's owner (the backend's `can_delete`).
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, MessageCircle } from "lucide-react";

import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { deleteComment, fetchComments, postComment } from "@/lib/api";
import type { CommentOut } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

const MAX_LENGTH = 1000;

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h`;
  if (s < 30 * 86_400) return `${Math.floor(s / 86_400)}d`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function Compose({
  placeholder,
  submitLabel,
  autoFocus,
  onSubmit,
  onCancel,
}: {
  placeholder: string;
  submitLabel: string;
  autoFocus?: boolean;
  onSubmit: (body: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = body.trim();

  const submit = async () => {
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(trimmed);
      setBody("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't post that");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value.slice(0, MAX_LENGTH))}
        onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && void submit()}
        placeholder={placeholder}
        rows={2}
        autoFocus={autoFocus}
        className="block w-full resize-y rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-3 py-2 text-[13px] text-[var(--mtv-text)] placeholder:text-[var(--mtv-text-2)]/60 focus:border-[var(--mtv-gold)]/60 focus:outline-none"
      />
      <div className="flex items-center justify-end gap-2">
        {error && <p className="mr-auto text-xs text-[var(--mtv-red)]">{error}</p>}
        {body.length > MAX_LENGTH * 0.8 && (
          <span className="mr-auto text-[11px] text-[var(--mtv-text-2)]">
            {body.length}/{MAX_LENGTH}
          </span>
        )}
        {onCancel && (
          <button type="button" onClick={onCancel} className="rounded-lg px-3 py-1.5 text-[13px] text-[var(--mtv-text-2)] hover:text-[var(--mtv-text)]">
            Cancel
          </button>
        )}
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!trimmed || busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--mtv-gold)] px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-on-gold)] disabled:opacity-40"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

function CommentRow({
  comment,
  canReply,
  onReply,
  onDelete,
  reply,
}: {
  comment: CommentOut;
  canReply: boolean;
  onReply?: () => void;
  onDelete: (c: CommentOut) => Promise<void>;
  reply?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <div className={cn("flex gap-3", reply && "pl-11")}>
      {comment.user.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={comment.user.avatar_url} alt="" className={cn("shrink-0 rounded-full", reply ? "h-6 w-6" : "h-8 w-8")} />
      ) : (
        <span className={cn("shrink-0 rounded-full bg-[var(--mtv-surface-high)]", reply ? "h-6 w-6" : "h-8 w-8")} />
      )}
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-xs text-[var(--mtv-text-2)]">
          <span className="font-semibold text-[var(--mtv-text)]">@{comment.user.username}</span> · {timeAgo(comment.created_at)}
        </p>
        <p className="whitespace-pre-wrap break-words text-[13px]">{comment.body}</p>
        <div className="flex items-center gap-3 text-xs text-[var(--mtv-text-2)]">
          {canReply && onReply && (
            <button type="button" onClick={onReply} className="hover:text-[var(--mtv-text)]">
              Reply
            </button>
          )}
          {comment.can_delete &&
            (confirming ? (
              <>
                <button
                  type="button"
                  disabled={deleting}
                  onClick={async () => {
                    setDeleting(true);
                    await onDelete(comment).finally(() => setDeleting(false));
                  }}
                  className="font-semibold text-[var(--mtv-red)]"
                >
                  {deleting ? "Deleting…" : "Delete"}
                </button>
                <button type="button" onClick={() => setConfirming(false)} className="hover:text-[var(--mtv-text)]">
                  Keep
                </button>
              </>
            ) : (
              <button type="button" onClick={() => setConfirming(true)} className="hover:text-[var(--mtv-red)]">
                Delete
              </button>
            ))}
        </div>
      </div>
    </div>
  );
}

export function Comments({ clipId }: { clipId: string }) {
  const me = useCurrentUser();
  const meId = me?.id ?? null;
  const [items, setItems] = useState<CommentOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replyingTo, setReplyingTo] = useState<string | null>(null);

  // Reload when the acting user changes: `can_delete` depends on who's asking.
  const load = useCallback(() => {
    let cancelled = false;
    fetchComments(clipId).then(
      (page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setCursor(page.next_cursor);
        setError(null);
      },
      (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Couldn't load comments")
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId, meId]);
  useEffect(() => load(), [load]);

  const more = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await fetchComments(clipId, cursor);
      setItems((list) => [...(list ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  };

  const add = async (body: string) => {
    const c = await postComment(clipId, body);
    setItems((list) => [{ ...c, replies: [], reply_count: 0, can_delete: true }, ...(list ?? [])]);
    setTotal((n) => n + 1);
  };

  const addReply = async (parentId: string, body: string) => {
    const r = await postComment(clipId, body, parentId);
    setItems((list) =>
      (list ?? []).map((c) =>
        c.id === r.parent_id
          ? { ...c, replies: [...c.replies, { ...r, can_delete: true }], reply_count: c.reply_count + 1 }
          : c
      )
    );
    setTotal((n) => n + 1);
    setReplyingTo(null);
  };

  const remove = async (target: CommentOut) => {
    try {
      await deleteComment(target.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete that");
      return;
    }
    setItems((list) => {
      if (!target.parent_id) return (list ?? []).filter((c) => c.id !== target.id);
      return (list ?? []).map((c) =>
        c.id === target.parent_id
          ? { ...c, replies: c.replies.filter((r) => r.id !== target.id), reply_count: c.reply_count - 1 }
          : c
      );
    });
    // Deleting a top-level comment removes its replies too.
    setTotal((n) => Math.max(0, n - 1 - (target.parent_id ? 0 : target.replies.length)));
  };

  return (
    <section className="space-y-4 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <MessageCircle className="h-4 w-4 text-[var(--mtv-gold)]" />
        Comments{items && <span className="font-normal text-[var(--mtv-text-2)]">· {total}</span>}
      </h3>

      {me ? (
        <Compose placeholder={`Comment as @${me.username}…`} submitLabel="Comment" onSubmit={add} />
      ) : (
        <ChooseUserNotice action="comment" />
      )}

      {error && <p className="text-xs text-[var(--mtv-red)]">{error}</p>}
      {!items && !error && (
        <p className="flex items-center gap-2 text-xs text-[var(--mtv-text-2)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading comments…
        </p>
      )}
      {items?.length === 0 && <p className="text-xs text-[var(--mtv-text-2)]">No comments yet. Be the first.</p>}

      <div className="space-y-5">
        {items?.map((c) => (
          <div key={c.id} className="space-y-3">
            <CommentRow comment={c} canReply={Boolean(me)} onReply={() => setReplyingTo(c.id)} onDelete={remove} />
            {c.replies.map((r) => (
              <CommentRow key={r.id} comment={r} canReply={false} onDelete={remove} reply />
            ))}
            {replyingTo === c.id && (
              <div className="pl-11">
                <Compose
                  placeholder={`Reply to @${c.user.username}…`}
                  submitLabel="Reply"
                  autoFocus
                  onSubmit={(body) => addReply(c.id, body)}
                  onCancel={() => setReplyingTo(null)}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {cursor && (
        <button
          type="button"
          onClick={() => void more()}
          disabled={loadingMore}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--mtv-text-2)] hover:text-[var(--mtv-text)]"
        >
          {loadingMore && <Loader2 className="h-3 w-3 animate-spin" />}
          Load more comments
        </button>
      )}
    </section>
  );
}

"""Per-session single-writer ordered ticket queue (#1353 / ADR 0149).

Design contract:
- Trailing legs (extraction / highlight / mindreading) claim a ticket at start
  (barrier/inflight ordering). LLM stays parallel outside the queue (P5).
  DB critical sections run through the ticket execution seam (`run` /
  `TicketedWriteGate`) which orders only **write turns** among open tickets —
  not whole-leg completion — so peer trails do not serialize each other's LLM.
  The ticket is completed only after the leg finishes (success, fail, or
  cancel → empty vacate).
- Month-advance is a barrier ticket: claimed after all already-issued tickets,
  so prior legs drain naturally before close/settle runs (`wait_prior` = full
  prior complete). Post-barrier claims wait on the open barrier via the write
  seam (barrier key blocks write turns until barrier vacates).
- write_gate remains the exclusive write lock (CLI + Web share one session
  queue). Queue length / open tickets are the sole inflight fact source.
- Cancel vacates without resurrecting work (ADR 0038 retract).
- Barrier release waits only on worker/provider terminal vacate of prior
  tickets (K10a: no elapsed forging of healthy legs into failure). True hang
  termination belongs to the provider/worker seam that owns the call; once
  that seam reaches a terminal state the worker finally-vacates and the
  barrier proceeds into the existing error-pack / night-OPEN path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Optional, TypeVar

T = TypeVar("T")


class TicketCancelled(Exception):
    """Ticket was cancelled before or during its work; caller must not write."""


@dataclass
class WriteTicket:
    """Opaque ordering ticket. seq is monotonic per queue; key is optional cancel tag."""

    seq: int
    key: Optional[Hashable] = None
    cancelled: bool = False
    _done: bool = field(default=False, repr=False, compare=False)
    # Write-turn state (P5): only serializes DB critical sections, not whole-leg LLM.
    _awaiting_write: bool = field(default=False, repr=False, compare=False)
    _in_write: bool = field(default=False, repr=False, compare=False)


def _is_barrier_ticket(ticket: WriteTicket) -> bool:
    """Barrier tickets block later write turns until they fully vacate."""
    key = ticket.key
    if key == ("barrier",):
        return True
    # claim/barrier both tag barrier as tuple; tolerate bare string marks in tests.
    return key == "barrier" or (
        isinstance(key, tuple) and len(key) > 0 and key[0] == "barrier"
    )


class TicketedWriteGate:
    """Lock-like production write seam: wait_write_turn → write_gate + cancel check.

    Drop-in for `threading.Lock` at trailing-leg write sites (`with gate` / acquire).
    Orders only concurrent write turns (and open barriers) — peer legs keep LLM
    parallel (P5). Does not complete the ticket — caller still complete()/vacate()
    in finally.
    """

    def __init__(
        self,
        queue: "SessionWriteQueue",
        ticket: WriteTicket,
    ) -> None:
        self._queue = queue
        self._ticket = ticket
        self._held = False

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if not blocking:
            # Non-blocking ticketed acquire is not meaningful (order wait is the point).
            raise RuntimeError("TicketedWriteGate only supports blocking acquire")
        del timeout  # lock timeout unused; order wait is terminal-state only
        self._queue.wait_write_turn(self._ticket)
        try:
            self._queue.write_gate.acquire()
        except BaseException:
            self._queue.finish_write_turn(self._ticket)
            raise
        self._held = True
        if self._ticket.cancelled or self._ticket._done:
            self._held = False
            self._queue.write_gate.release()
            self._queue.finish_write_turn(self._ticket)
            raise TicketCancelled(f"ticket {self._ticket.seq} cancelled")
        return True

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self._queue.write_gate.release()
        finally:
            self._queue.finish_write_turn(self._ticket)

    def __enter__(self) -> "TicketedWriteGate":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


class SessionWriteQueue:
    """Ordered ticket ledger + exclusive write_gate for one GameSession."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._next_seq = 1
        # seq -> ticket still open (not completed/vacated)
        self._open: dict[int, WriteTicket] = {}
        # key -> set of open seqs (for cancel-by-key / retract)
        self._by_key: dict[Hashable, set[int]] = {}
        # Exclusive DB write lock — write_gate semantics live here.
        self.write_gate = threading.Lock()
        # Lifecycle seal: reject new claims (menu drain / session teardown).
        self._sealed = False

    # ── ticket lifecycle ───────────────────────────────────────────────

    def seal(self) -> None:
        """Reject further claims (lifecycle drain). Open tickets still complete."""
        with self._cond:
            self._sealed = True
            self._cond.notify_all()

    def unseal(self) -> None:
        """Allow claims again (tests / rare reopen)."""
        with self._cond:
            self._sealed = False

    def is_sealed(self) -> bool:
        with self._cond:
            return bool(self._sealed)

    def has_open_barrier(self) -> bool:
        """True while a month-advance/close barrier ticket is still open."""
        with self._cond:
            return any(_is_barrier_ticket(t) for t in self._open.values())

    def claim(self, key: Optional[Hashable] = None) -> Optional[WriteTicket]:
        """Synchronously take the next ordering ticket (trail start / barrier).

        Returns None when sealed (lifecycle drain — caller must not start work).
        """
        with self._cond:
            if self._sealed:
                return None
            seq = self._next_seq
            self._next_seq += 1
            ticket = WriteTicket(seq=seq, key=key)
            self._open[seq] = ticket
            if key is not None:
                self._by_key.setdefault(key, set()).add(seq)
            return ticket

    def complete(self, ticket: Optional[WriteTicket]) -> None:
        """Release ticket slot (success or empty vacate). Idempotent."""
        if ticket is None:
            return
        with self._cond:
            self._finish_locked(ticket)

    def vacate(self, ticket: Optional[WriteTicket]) -> None:
        """Empty release on fail/cancel — same as complete (order advances)."""
        self.complete(ticket)

    def cancel(self, ticket: Optional[WriteTicket]) -> None:
        """Mark cancelled and vacate. In-flight legs must check ticket.cancelled."""
        if ticket is None:
            return
        with self._cond:
            ticket.cancelled = True
            self._finish_locked(ticket)

    def cancel_key(self, key: Hashable) -> int:
        """Cancel all open tickets tagged with key. Returns how many vacated."""
        with self._cond:
            seqs = list(self._by_key.get(key, ()))
            n = 0
            for seq in seqs:
                ticket = self._open.get(seq)
                if ticket is None:
                    continue
                ticket.cancelled = True
                self._finish_locked(ticket)
                n += 1
            return n

    def _finish_locked(self, ticket: WriteTicket) -> None:
        if ticket._done:
            return
        ticket._done = True
        self._open.pop(ticket.seq, None)
        if ticket.key is not None:
            bucket = self._by_key.get(ticket.key)
            if bucket is not None:
                bucket.discard(ticket.seq)
                if not bucket:
                    self._by_key.pop(ticket.key, None)
        self._cond.notify_all()

    # ── barrier / waits ────────────────────────────────────────────────

    def wait_prior(self, ticket: WriteTicket) -> None:
        """Block until every open ticket with seq < ticket.seq is finished.

        Full prior-complete wait — used by barrier admission (K10a). Cancelled
        ticket → TicketCancelled. No elapsed failure classification.
        Write seams use wait_write_turn instead (P5: do not serialize peer LLM).
        """
        with self._cond:
            while True:
                if ticket.cancelled or ticket._done:
                    raise TicketCancelled(f"ticket {ticket.seq} cancelled")
                priors = [seq for seq in self._open if seq < ticket.seq]
                if not priors:
                    return
                self._cond.wait()

    def wait_write_turn(self, ticket: WriteTicket) -> None:
        """Block only for prior write turns / open barriers — not whole-leg LLM.

        A later ticket may enter its DB critical section while an earlier peer
        leg is still in LLM (ticket open but not awaiting/in write). Open
        barrier tickets always block later write turns until they vacate, so
        post-barrier claims cannot cross the barrier body.
        """
        with self._cond:
            if ticket.cancelled or ticket._done:
                raise TicketCancelled(f"ticket {ticket.seq} cancelled")
            ticket._awaiting_write = True
            self._cond.notify_all()
            try:
                while True:
                    if ticket.cancelled or ticket._done:
                        raise TicketCancelled(f"ticket {ticket.seq} cancelled")
                    blocked = False
                    for seq, prior in self._open.items():
                        if seq >= ticket.seq:
                            continue
                        if (
                            _is_barrier_ticket(prior)
                            or prior._in_write
                            or prior._awaiting_write
                        ):
                            blocked = True
                            break
                    if not blocked:
                        ticket._awaiting_write = False
                        ticket._in_write = True
                        self._cond.notify_all()
                        return
                    self._cond.wait()
            except BaseException:
                ticket._awaiting_write = False
                ticket._in_write = False
                self._cond.notify_all()
                raise

    def finish_write_turn(self, ticket: WriteTicket) -> None:
        """Release write-turn flags after leaving the DB critical section."""
        with self._cond:
            ticket._in_write = False
            ticket._awaiting_write = False
            self._cond.notify_all()

    def barrier(self, fn: Callable[[], T]) -> T:
        """Claim a barrier ticket after current claims; run fn when priors clear.

        Prior open tickets (trailing legs claimed earlier) must finish first
        (full complete via wait_prior). Tickets claimed after this barrier wait
        on the open barrier key via run()/TicketedWriteGate write turns — so
        they cannot cross the barrier body.

        Sealed queue: still waits for open priors, then runs fn (lifecycle/
        month-advance must proceed even when new claims are rejected).
        """
        with self._cond:
            seq = self._next_seq
            self._next_seq += 1
            ticket = WriteTicket(seq=seq, key=("barrier",))
            self._open[seq] = ticket
            self._by_key.setdefault(("barrier",), set()).add(seq)
        try:
            self.wait_prior(ticket)
            return fn()
        finally:
            self.complete(ticket)

    def wait_idle(self, *, timeout_s: Optional[float] = None) -> bool:
        """Wait until no open tickets remain. True if idle, False on timeout.

        timeout_s is only for lifecycle/menu drain probes (not barrier release).
        Barrier/write order never uses elapsed failure classification.
        """
        import time

        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        with self._cond:
            while self._open:
                if deadline is None:
                    self._cond.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)
            return True

    def inflight_count(self) -> int:
        with self._cond:
            return len(self._open)

    def ticketed_gate(self, ticket: WriteTicket) -> TicketedWriteGate:
        """Production write seam for a claimed ticket."""
        return TicketedWriteGate(self, ticket)

    def run(
        self,
        ticket: WriteTicket,
        fn: Callable[[], T],
    ) -> T:
        """Take a write turn, run fn under write_gate; caller completes the ticket.

        Write-turn ordered (not whole-leg wait_prior) so peer LLM stays parallel.
        Does not complete the ticket — legs may do LLM outside and only use
        this helper for the write section, then complete().
        """
        with self.ticketed_gate(ticket):
            return fn()

    def run_exclusive(self, fn: Callable[[], T]) -> T:
        """Claim + write-turn + write_gate + complete — one-shot exclusive write."""
        ticket = self.claim()
        if ticket is None:
            raise RuntimeError("write queue sealed")
        try:
            return self.run(ticket, fn)
        finally:
            self.complete(ticket)


# Lazy-install path is fixture/partial-wiring only (GameSession/WebGame eager).
# Module lock + double-check keeps concurrent first-touch from forking ledgers.
_INSTALL_LOCK = threading.Lock()


def get_session_write_queue(owner: Any) -> SessionWriteQueue:
    """Resolve the per-session queue from WebGame / GameSession / duck owner.

    Prefer owner._write_queue; else session._write_queue; else install a fresh
    queue on session (and mirror write_gate) so CLI/tests without explicit
    wiring still share one ledger.

    Production owners (GameSession.__init__, WebGame runtime) install eagerly;
    the lazy install below is fixture/partial-wiring only and is serialized by
    `_INSTALL_LOCK` (double-checked) so concurrent first-touch cannot fork two
    queues onto the same owner/session.

    If owner already has a bare `_write_gate` Lock (legacy fixtures), reuse that
    lock as the queue's write_gate so drain/barrier never diverge onto a second lock.

    Wiring assignments are fail-loud (ADR 0005): silent swallow here can fork
    owner/session onto different queue/gate ledgers and leak tickets.
    """
    q = getattr(owner, "_write_queue", None)
    if isinstance(q, SessionWriteQueue):
        return q
    session = getattr(owner, "session", None)
    if session is not None:
        q = getattr(session, "_write_queue", None)
        if isinstance(q, SessionWriteQueue):
            owner._write_queue = q
            # Keep owner._write_gate pointing at the same lock.
            owner._write_gate = q.write_gate
            return q
    with _INSTALL_LOCK:
        # Double-check after acquiring install lock.
        q = getattr(owner, "_write_queue", None)
        if isinstance(q, SessionWriteQueue):
            return q
        session = getattr(owner, "session", None)
        if session is not None:
            q = getattr(session, "_write_queue", None)
            if isinstance(q, SessionWriteQueue):
                owner._write_queue = q
                owner._write_gate = q.write_gate
                return q
        # Install on the most session-like object available.
        target = session if session is not None else owner
        q = SessionWriteQueue()
        # Reuse pre-existing write_gate Lock if present (fixture / partial wiring).
        existing_gate = getattr(owner, "_write_gate", None)
        if existing_gate is None and session is not None:
            existing_gate = getattr(session, "_write_gate", None)
        if existing_gate is not None and hasattr(existing_gate, "acquire"):
            q.write_gate = existing_gate  # type: ignore[assignment]
        target._write_queue = q  # type: ignore[attr-defined]
        target._write_gate = q.write_gate  # type: ignore[attr-defined]
        if session is not None and owner is not session:
            owner._write_queue = q
            owner._write_gate = q.write_gate
        return q

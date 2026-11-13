"""
Frame driver: bounded trace admission, cancellation and terminal
callbacks.
"""

import time
import unreal as u
from .editor_scene_adapter import HitResultField
from .rooms.scan_budget import (
    MILLISECONDS_PER_SECOND,
    BudgetExceeded,
    RunBudget,
    settings,
)
from .rooms.candidate import Candidate

# Limit each Slate callback's work in both time and immediately ready batches.
CALLBACK_SECONDS = 0.00075
MAX_READY_BATCHES = 8
TRACE_BATCH_TIMEOUT_SECONDS = 10


class EditorHit(tuple):
    """RayHitField record plus the component used by thick-shell validation."""

    def __new__(cls, fields):
        point = fields[HitResultField.IMPACT_POINT].to_tuple()
        normal = fields[HitResultField.IMPACT_NORMAL].to_tuple()
        hit = super().__new__(cls, (point, normal))
        hit.component = fields[HitResultField.HIT_COMPONENT]
        return hit


class ScanRunner:
    def __init__(self, seed, context, done, failed, stopped, started):
        self.seed, self.context = seed, context
        self.done, self.failed, self.stopped = done, failed, stopped
        self.budget = RunBudget(
            settings(context.get("budget_profile")), started
        )
        self.batch, self.handle, self.deadline = None, None, 0
        self.modes = set()
        self.terminal = False
        self.candidates = {}
        self.ray_starts, self.ray_ends = [], []

    def begin(self) -> None:
        try:
            batch_class = getattr(u, "InteriorFitTraceBatch", None)
            if not (
                hasattr(u, "InteriorFitTraceRequest")
                and hasattr(batch_class, "submit_request")
                and hasattr(batch_class, "cancel")
            ):
                raise RuntimeError(
                    "Interior Fit 的 C++ 模块需要重新编译；"
                    "请关闭编辑器并重编 Development Editor。"
                )
            self.handle = u.register_slate_post_tick_callback(self.tick)
        except Exception:
            self.context["scan"].close()
            raise

    def validate(self) -> None:
        c = self.context
        if (
            c["subsystem"].get_editor_world() != c["world"]
            or c["subsystem"].get_game_world()
            or not u.SystemLibrary.is_valid(self.seed)
        ):
            raise ValueError("World changed during scan")
        if self.seed.get_actor_location() != c["origin"]:
            raise ValueError("Seed moved during scan; select it and retry")
        self.budget.check_time()

    def next_rays(self):
        if self.batch is None:
            return next(self.context["scan"])
        if self.batch.pending:
            if time.monotonic() > self.deadline:
                raise ValueError(
                    "Editor world did not dispatch asynchronous physics "
                    "results"
                )
            return None
        self.modes.add("frame_sliced" if self.batch.frame_sliced else "async")
        hits = self.batch.hits
        protected = self.context.get("protected")
        if protected:
            hits = u.InteriorFitLibrary.constrain_room_rays(
                protected, self.ray_starts, self.ray_ends, hits
            )
        values = [hit.to_tuple() for hit in hits]
        editor_hits = [
            EditorHit(fields) if fields[HitResultField.BLOCKING_HIT] else None
            for fields in values
        ]
        return self.context["scan"].send(editor_hits)

    def tick(self, delta: float) -> None:
        if self.terminal:
            return
        try:
            try:
                self.validate()
                end = time.monotonic() + CALLBACK_SECONDS
                for _ in range(MAX_READY_BATCHES):
                    if not self.advance(end):
                        return
            except StopIteration as complete:
                self.finish(complete.value)
            except BudgetExceeded as error:
                self.review_best(error)
        except Exception as error:
            self.fail(error)

    def advance(self, end: float) -> bool:
        """Consume ready work only; never poll a pending batch in a tight loop.
        """
        rays = self.next_rays()
        while isinstance(rays, Candidate):
            self.candidates[rays.key] = rays
            rays = next(self.context["scan"])
        if rays is None:
            return False
        self.budget.admit(len(rays))
        starts, ends = (
            [u.Vector(*a) for a, b in rays],
            [u.Vector(*b) for a, b in rays],
        )
        self.ray_starts, self.ray_ends = starts, ends
        remaining_ms = max(
            0, (end - time.monotonic()) * MILLISECONDS_PER_SECOND
        )
        request = u.InteriorFitTraceRequest()
        request.starts = starts
        request.ends = ends
        request.ignored = self.context["ignored"]
        request.immediate_budget_ms = remaining_ms
        self.batch = u.InteriorFitTraceBatch.submit_request(self.seed, request)
        if not self.batch:
            raise ValueError("Unreal rejected the trace batch")
        self.deadline = time.monotonic() + TRACE_BATCH_TIMEOUT_SECONDS
        return not self.batch.pending and time.monotonic() < end

    def stop(self, status: str) -> None:
        self.terminal = True
        if self.batch:
            self.batch.cancel()
        if self.handle is not None:
            u.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        self.stopped(self.budget.snapshot(status))

    def finish(self, result):
        try:
            self.budget.check_time()
        except BudgetExceeded as error:
            self.review_best(error)
            return
        result["trace_modes"] = sorted(self.modes)
        result["scan_budget"] = self.budget.snapshot("complete")
        if self.context["policy"]:
            result["authoring_budget"] = self.context["policy"]
        self.publish(result, "complete")

    def review_best(self, reason: BudgetExceeded) -> None:
        """Review the best candidate collected within budget."""
        if not self.candidates:
            self.fail(
                ValueError(str(reason) + " 尚无封闭候选；请调整起点或分区。")
            )
            return
        chosen = max(self.candidates.values(), key=lambda c: c.priority())
        result = dict(
            chosen.result,
            rays=self.budget.rays,
            preview_required=True,
            budget_fallback=str(reason),
            candidate_checks=chosen.checks,
            trace_modes=sorted(self.modes),
            scan_budget=self.budget.snapshot("review"),
        )
        if self.context["policy"]:
            result["authoring_budget"] = self.context["policy"]
        self.context["scan"].close()
        self.publish(result, "review")

    def publish(self, result, status):
        # Review can start another scan. Release this runner before calling it.
        self.stop(status)
        try:
            self.done(result)
        except Exception as error:
            self.failed(str(error))

    def fail(self, error: Exception) -> None:
        if self.terminal:
            raise error
        try:
            self.context["scan"].close()
        finally:
            self.stop("stopped")
            self.failed(str(error))

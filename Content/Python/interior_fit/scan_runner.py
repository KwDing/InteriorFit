"""Frame driver: bounded trace admission, cancellation and terminal callbacks."""
import time
import unreal as u
from .rooms.scan_budget import RunBudget, BudgetExceeded, settings
from .rooms.candidate import Candidate

CALLBACK_SECONDS = .00075
MAX_READY_BATCHES = 8


class EditorHit(tuple):
    def __new__(cls, value):
        hit = super().__new__(cls,(value[5].to_tuple(),value[7].to_tuple()))
        hit.component = value[10]
        return hit


class ScanRunner:
    def __init__(self, seed, context, done, failed, stopped, started):
        self.seed,self.context = seed,context
        self.done,self.failed,self.stopped = done,failed,stopped
        self.budget = RunBudget(settings(context.get('budget_profile')),started)
        self.batch,self.handle,self.deadline = None,None,0
        self.modes = set()
        self.terminal = False
        self.candidates = {}
        self.ray_starts,self.ray_ends = [],[]

    def begin(self):
        if not hasattr(u.InteriorFitTraceBatch,'cancel'):
            self.fail(ValueError('Interior Fit 的 C++ 模块需要重新编译；请关闭编辑器并重编 Development Editor。'))
            return
        self.handle = u.register_slate_post_tick_callback(self.tick)

    def validate(self):
        c = self.context
        if c['subsystem'].get_editor_world()!=c['world'] or c['subsystem'].get_game_world() or not u.SystemLibrary.is_valid(self.seed):
            raise ValueError('World changed during scan')
        if self.seed.get_actor_location()!=c['origin']:
            raise ValueError('Seed moved during scan; select it and retry')
        self.budget.check_time()

    def next_rays(self):
        if self.batch is None:
            return next(self.context['scan'])
        if self.batch.pending:
            if time.monotonic()>self.deadline:
                raise ValueError('Editor world did not dispatch asynchronous physics results')
            return None
        self.modes.add('frame_sliced' if self.batch.frame_sliced else 'async')
        hits = self.batch.hits
        protected = self.context.get('protected')
        if protected:
            hits = u.InteriorFitLibrary.constrain_room_rays(protected,self.ray_starts,self.ray_ends,hits)
        values = [hit.to_tuple() for hit in hits]
        return self.context['scan'].send([EditorHit(v) if v[0] else None for v in values])

    def tick(self, delta):
        if self.terminal:
            return
        try:
            self.validate()
            end = time.monotonic()+CALLBACK_SECONDS
            for _ in range(MAX_READY_BATCHES):
                if not self.advance(end):
                    return
        except StopIteration as complete:
            self.finish(complete.value)
        except BudgetExceeded as error:
            self.review_best(error)
        except Exception as error:
            self.fail(error)

    def advance(self, end):
        """Consume ready work only; never poll a pending batch in a tight loop."""
        rays = self.next_rays()
        while isinstance(rays,Candidate):
            self.candidates[rays.key] = rays
            rays = next(self.context['scan'])
        if rays is None:
            return False
        self.budget.admit(len(rays))
        starts,ends = [u.Vector(*a) for a,b in rays],[u.Vector(*b) for a,b in rays]
        self.ray_starts,self.ray_ends = starts,ends
        remaining_ms = max(0,(end-time.monotonic())*1000)
        self.batch = u.InteriorFitTraceBatch.submit(self.seed,starts,ends,self.context['ignored'],remaining_ms)
        if not self.batch:
            raise ValueError('Unreal rejected the trace batch')
        self.deadline = time.monotonic()+10
        return not self.batch.pending and time.monotonic()<end

    def stop(self, status):
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
        result['trace_modes'] = sorted(self.modes)
        result['scan_budget'] = self.budget.snapshot('complete')
        if self.context['policy']:
            result['authoring_budget'] = self.context['policy']
        self.stop('complete')
        self.done(result)

    def review_best(self, reason):
        """Use the strongest available geometric evidence within the spent budget."""
        if not self.candidates:
            self.fail(ValueError(str(reason)+' 尚无封闭候选；请调整起点或分区。'))
            return
        chosen = max(self.candidates.values(),key=lambda c:c.priority())
        result = dict(chosen.result,rays=self.budget.rays,preview_required=True,
            budget_fallback=str(reason),candidate_checks=chosen.checks,
            trace_modes=sorted(self.modes),scan_budget=self.budget.snapshot('review'))
        if self.context['policy']:
            result['authoring_budget'] = self.context['policy']
        self.context['scan'].close()
        self.stop('review')
        self.done(result)

    def fail(self, error):
        if self.terminal:
            return
        try:
            self.context['scan'].close()
        finally:
            self.stop('stopped')
            self.failed(str(error))

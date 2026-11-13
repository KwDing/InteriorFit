"""Ordered ray batches and the engine-independent hit record layout."""

from enum import IntEnum
from typing import Generator, Optional, Sequence, TypeVar

# Flood-fill grid spacing in centimeters and its per-probe work limit.
STEP = 40
MAX_CELLS = 12000
# Must match MaxRaysPerBatch in InteriorFitTraceBatch.cpp.
BATCH_SIZE = 128
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class RayHitField(IntEnum):
    """Indices for (impact point, impact normal) from a ray generator driver.

    Drivers may send plain tuples. EditorHit adds collision component metadata.
    A miss is None. Point units are centimeters in the active coordinate frame.
    """

    POINT = 0
    NORMAL = 1


Ray = tuple[Sequence[float], Sequence[float]]
Hit = tuple[Sequence[float], Sequence[float]]
Result = TypeVar("Result")
RayQuery = Generator[Sequence[Ray], list[Optional[Hit]], Result]


def query(rays: Sequence[Ray]) -> RayQuery[list[Optional[Hit]]]:
    hits = []
    for start in range(0, len(rays), BATCH_SIZE):
        hits.extend((yield rays[start : start + BATCH_SIZE]))
    return hits


def _resume_workers(workers, groups, hits, results):
    pending = {}
    offset = 0
    for index, rays in groups:
        end = offset + len(rays)
        try:
            pending[index] = workers[index].send(hits[offset:end])
        except StopIteration as done:
            results[index] = done.value
        offset = end
    return pending


def together(workers: Sequence[RayQuery[Result]]) -> RayQuery[list[Result]]:
    """
    Co-schedule independent checks, preserving each generator's hit
    ordering.
    """
    results = [None] * len(workers)
    pending = {}
    try:
        for index, worker in enumerate(workers):
            try:
                pending[index] = next(worker)
            except StopIteration as done:
                results[index] = done.value
        while pending:
            groups = list(pending.items())
            hits = yield from query(
                [ray for _, rays in groups for ray in rays]
            )
            pending = _resume_workers(workers, groups, hits, results)
    finally:
        for worker in workers:
            worker.close()
    return results

STEP = 40
MAX_CELLS = 12000
BATCH_SIZE = 128
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def query(rays):
    hits = []
    for start in range(0, len(rays), BATCH_SIZE):
        hits.extend((yield rays[start : start + BATCH_SIZE]))
    return hits


def together(workers):
    """Co-schedule independent checks, preserving each generator's hit ordering."""
    results = [None]*len(workers)
    pending = {}
    for index,worker in enumerate(workers):
        try:
            pending[index] = next(worker)
        except StopIteration as done:
            results[index] = done.value
    try:
        while pending:
            groups = list(pending.items())
            hits = yield from query([ray for _,rays in groups for ray in rays])
            pending,offset = {},0
            for index,rays in groups:
                answers = hits[offset:offset+len(rays)]
                offset += len(rays)
                try:
                    pending[index] = workers[index].send(answers)
                except StopIteration as done:
                    results[index] = done.value
    finally:
        for worker in workers:
            worker.close()
    return results

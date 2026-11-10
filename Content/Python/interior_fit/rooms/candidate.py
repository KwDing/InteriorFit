"""Complete geometric candidates with explicit evidence, never a fabricated IoU."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Candidate:
    result: dict
    checks: dict
    key: tuple

    def mapped(self, result):
        return replace(self,result=result)

    def priority(self):
        values = list(self.checks.values())
        return values.count('conflict')==0,values.count('passed'),-values.count('pending')


def prism(frame, roof, ring, count):
    outline = [(x,y,0) for x,y in ring]
    return dict(model='wall_plane_prism',origin=frame.origin,axis_x=frame.x,axis_z=frame.z,
                floor=0,roof=roof,local_outline=outline,outline=[frame.world(p) for p in outline],columns=count)


def offer(result, **checks):
    key = (result['model'],tuple(result['origin']),tuple(result['axis_x']),tuple(result['axis_z']),result['roof'],
           tuple(tuple(p) for p in result['local_outline']))
    return Candidate(result,checks,key)

"""Fit the enclosing stairwell, verifying a connected rise between two storeys."""
from collections import Counter
from .. import room_contour
from ..rooms.rays import query
from ..rooms.frame import FloorFrame, cross
from ..rooms.plane_cells import inside
from ..rooms.candidate import Candidate
from . import stair_layers


def enclosure(seed):
    """Do not publish ordinary room candidates as verified stairwell fallbacks."""
    worker=room_contour.scan(seed)
    try:
        request=next(worker)
        while True:
            if isinstance(request,Candidate):
                request=next(worker)
                continue
            request=worker.send((yield request))
    except StopIteration as done:
        return done.value
    finally:
        worker.close()


def columns(result):
    ring=[p[:2] for p in result['local_outline']]
    xs,ys=zip(*ring)
    frame=FloorFrame(result['origin'],result['axis_z'])
    frame.x=result['axis_x'];frame.y=cross(frame.z,frame.x)
    points={}
    for i in range(5):
        for j in range(9):
            x=min(xs)+15+(max(xs)-min(xs)-30)*i/4
            y=min(ys)+15+(max(ys)-min(ys)-30)*j/8
            if inside(ring,(x,y)):
                points[i,j]=(x,y)
    return frame,points


def connected_levels(points,heights,frame,stats):
    rays,edges=[],[]
    for a in heights:
        for dx,dy in ((1,0),(0,1)):
            b=(a[0]+dx,a[1]+dy)
            if b not in heights or abs(heights[a]-heights[b])>110:continue
            z=max(heights[a],heights[b])+100
            rays.append((frame.world((*points[a],z)),frame.world((*points[b],z))))
            edges.append((a,b))
    hits=yield from stair_layers.cast(rays,stats)
    graph={key:set() for key in heights}
    for (a,b),hit in zip(edges,hits):
        if not hit:graph[a].add(b);graph[b].add(a)
    lowest=min(heights,key=heights.get)
    reached={lowest};frontier={lowest}
    while frontier:
        frontier={b for a in frontier for b in graph[a]}-reached
        reached.update(frontier)
    levels=Counter(round(heights[key]/10)*10 for key in reached)
    landings=[z for z,count in levels.items() if count>=2]
    if len(landings)<2 or max(landings)-min(landings)<220 or len(levels)<4:
        raise ValueError('未证实连接两层平台的连续升高路径')
    return [min(landings),max(landings)]


def scan(seed):
    result=yield from enclosure(seed)
    if result['model']!='wall_plane_prism' or result['roof']-result['floor']<420 or result['axis_z'][2]<.99:
        raise ValueError('需要封闭的直立跨层楼梯围护空间')
    frame,points=columns(result)
    rays=[(frame.world((*p,result['roof']-8)),frame.world((*p,result['floor']-12))) for p in points.values()]
    hits=yield from query(rays)
    heights={key:frame.local(hit[0])[2] for key,hit in zip(points,hits) if hit and hit[1][2]>.6}
    if not heights:raise ValueError('未测到楼梯踏面')
    stats=dict(rays=len(rays))
    try:
        levels=yield from connected_levels(points,heights,frame,stats)
    except ValueError:
        levels,evidence=yield from stair_layers.verify(points,hits,frame,result['floor'],seed,stats)
        result['stair_layer_evidence']=evidence
    result.update(stair_enclosure=True,connected_landing_heights_cm=[frame.origin[2]+z for z in levels],
                  rays=result['rays']+stats['rays'])
    return result

"""Ear clipping for a simple concave ring; never replace a concavity with a fan."""


def turn(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def in_triangle(p,a,b,c):
    return min(turn(a,b,p),turn(b,c,p),turn(c,a,p))>=-1.e-8


def cap_triangles(ring):
    """Return CCW index triples, including boundary points when rejecting an ear."""
    area=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(ring,ring[1:]+ring[:1]))
    if abs(area)<1.e-8:raise ValueError('Room 轮廓面积为零')
    pending=list(range(len(ring)))
    if area<0:pending.reverse()
    triangles=[]
    while len(pending)>3:
        ear=None
        for index,b in enumerate(pending):
            a,c=pending[index-1],pending[(index+1)%len(pending)]
            if turn(ring[a],ring[b],ring[c])<=1.e-8:continue
            if any(in_triangle(ring[p],ring[a],ring[b],ring[c]) for p in pending if p not in (a,b,c)):continue
            ear=index;triangles.append((a,b,c));break
        if ear is None:raise ValueError('Room 轮廓不能安全三角化：可能自交或含重复点')
        pending.pop(ear)
    if turn(*(ring[i] for i in pending))<=1.e-8:raise ValueError('Room 封口包含退化三角形')
    triangles.append(tuple(pending))
    return triangles


def prism_buffers(ring,height):
    if height<=0:raise ValueError('Room 高度必须为正')
    caps=cap_triangles(ring)
    n=len(ring)
    vertices=[(x,y,z) for z in (0,height) for x,y in ring]
    triangles=[(a,c,b) for a,b,c in caps]+[(a+n,b+n,c+n) for a,b,c in caps]
    ccw=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(ring,ring[1:]+ring[:1]))>0
    for a in range(n):
        b=(a+1)%n
        side=[(a,b,b+n),(a,b+n,a+n)]
        triangles.extend(side if ccw else [(x,z,y) for x,y,z in side])
    return vertices,triangles

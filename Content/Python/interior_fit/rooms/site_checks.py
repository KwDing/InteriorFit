"""Separate roof-covered wall thickness from evidence of unexplored room air."""
import math
from . import plane_cells
from .rays import query


def closest_edge(ring, point):
    candidates = []
    for a,b in zip(ring,ring[1:]+ring[:1]):
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = math.hypot(dx,dy)
        t = max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(length*length)))
        foot = a[0]+t*dx,a[1]+t*dy
        candidates.append((math.dist(point,foot),foot,(-dy/length,dx/length)))
    return min(candidates,key=lambda item:item[0])


def exclude_wall_sites(frame, roof, ring, sites, points):
    """Only exclude a near-exterior roof point after measuring its actual wall.

    A ceiling can cover the wall's thickness. It does not make that material
    room air. Keep the existing 4 cm matching tolerance for all other points.
    """
    suspects,rays = [],[]
    for key in sorted(sites):
        if plane_cells.inside(ring,points[key]) or plane_cells.near_edge(ring,points[key]):
            continue
        distance,(x,y),(nx,ny) = closest_edge(ring,points[key])
        if not 4 < distance <= 12:
            continue
        suspects.append((key,x,y,nx,ny))
        rays.append((frame.world((x+18*nx,y+18*ny,roof-5)),frame.world((x-18*nx,y-18*ny,roof-5))))
    ignored = set()
    for (key,x,y,nx,ny),hit in zip(suspects,(yield from query(rays))):
        if not hit:
            continue
        px,py,_ = frame.local(hit[0])
        hx,hy,_ = frame.direction(hit[1])
        if abs((px-x)*nx+(py-y)*ny)<4 and hx*nx+hy*ny>.995:
            ignored.add(key)
    return sites-ignored,{key:p for key,p in points.items() if key not in ignored},len(ignored)

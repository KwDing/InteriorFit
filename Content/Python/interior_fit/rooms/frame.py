import math


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def unit(v):
    length = math.sqrt(dot(v, v))
    return tuple(x / length for x in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


class FloorFrame:
    """Orthonormal room coordinates, with Z perpendicular to the measured floor."""

    def __init__(self, origin, normal):
        self.origin = origin
        self.z = unit(normal)
        self.y = unit(cross(self.z, (1, 0, 0)))
        self.x = cross(self.y, self.z)

    def world(self, p):
        return tuple(self.origin[i] + self.x[i] * p[0] + self.y[i] * p[1] + self.z[i] * p[2] for i in range(3))

    def direction(self, v):
        return tuple(dot(v, axis) for axis in (self.x, self.y, self.z))

    def local(self, p):
        return self.direction(tuple(x - y for x, y in zip(p, self.origin)))

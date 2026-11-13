"""Assemble fitted mesh data with Unreal face winding."""


def result(frame, model, outline, vertices, faces):
    triangles = [
        (face[0], face[i + 1], face[i])
        for face in faces
        for i in range(1, len(face) - 1)
    ]
    return dict(
        model=model,
        columns=0,
        floor=0,
        roof=max(p[2] for p in vertices),
        origin=frame.origin,
        axis_x=frame.x,
        axis_z=frame.z,
        local_outline=outline,
        outline=[frame.world(p) for p in outline],
        vertices=vertices,
        triangles=triangles,
    )

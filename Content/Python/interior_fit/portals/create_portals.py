"""Create validated Portals in one editor transaction."""

import unreal as u

from .validate_portals import validate_batch


def spawn_portal(world, cls, row):
    return u.InteriorFitLibrary.create_box_volume(
        world,
        cls,
        u.Transform(
            location=u.Vector(*row["center"]),
            rotation=u.Rotator(yaw=row["yaw"]),
        ),
        u.Vector(*row["half_extent"]),
    )


def create_batch(data):
    cls = getattr(u, "AkAcousticPortal", None)
    if cls is None:
        raise RuntimeError(
            "Enable Wwise integration to create acoustic Portals"
        )
    world, actors, rows = validate_batch(data)
    created = []
    with u.ScopedEditorTransaction("Interior Fit: Create Portals"):
        try:
            for row in rows:
                portal = spawn_portal(world, cls, row)
                if not portal:
                    raise RuntimeError("Native Portal creation failed")
                created.append(portal)
                portal.set_actor_label(row["name"])
                portal.set_folder_path("InteriorFit/Portals")
                component = portal.get_editor_property("portal")
                state_type = type(
                    component.get_editor_property("initial_state")
                )
                component.set_editor_property(
                    "initial_state",
                    state_type.OPEN if row["open"] else state_type.CLOSED,
                )
                portal.enable_portal() if row[
                    "open"
                ] else portal.disable_portal()
            actors.set_selected_level_actors(created)
        except Exception as error:
            surviving = []
            for actor in reversed(created):
                label = actor.get_actor_label()
                if not actors.destroy_actor(actor):
                    surviving.append(label)
            if surviving:
                raise RuntimeError(
                    str(error)
                    + "; rollback could not remove: "
                    + ", ".join(surviving)
                ) from error
            raise
    u.InteriorFitLibrary.draw_opening_previews(world, "[]")
    return created

"""
Selected-actor interior preview and conservative native Room creation;
no automatic save.
"""

import unreal as u


from .rooms.authoring.box_fit_controller import (
    create_selected as create_selected,
    preview_selected as preview_selected,
)


def clear_preview() -> None:
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    if not u.InteriorFitLibrary.clear_surface_previews(world):
        raise RuntimeError("预览未能完全清除；请退出 PIE 后重试。")
    u.InteriorFitLibrary.draw_spline_preview_with_style(
        world,
        [],
        u.InteriorFitSplineClosure.OPEN,
        u.InteriorFitSplineBudgetStatus.WITHIN_BUDGET,
    )
    u.InteriorFitLibrary.draw_area_preview(world, "")
    u.InteriorFitLibrary.draw_preview(
        world, u.Transform(), u.Vector(0, 0, 0), u.LinearColor()
    )
    u.InteriorFitLibrary.draw_opening_previews(world, "[]")


def find_openings_selected() -> None:
    from interior_fit.openings import open_selected

    open_selected(False)


def fit_openings_selected() -> None:
    from interior_fit.openings import open_selected

    open_selected(True)


def fit_polygon_selected() -> None:
    from interior_fit.rooms.authoring.polygon_fit_controller import selected

    selected()


def merge_selected_rooms() -> None:
    from interior_fit.rooms.authoring.merge_box_rooms import selected

    selected()


def fit_stair_selected() -> None:
    from interior_fit.rooms.authoring.polygon_fit_controller import selected
    from interior_fit.floors.scan_stairs import scan

    selected(scan)


def fit_lake_geometry() -> None:
    from interior_fit.surfaces.fit_selected_geometry import selected

    selected("lake")


def fit_river_geometry() -> None:
    from interior_fit.surfaces.fit_selected_geometry import selected

    selected("river")


def fit_area_geometry() -> None:
    from interior_fit.surfaces.fit_selected_geometry import selected

    selected("area")


def fit_floor_selected() -> None:
    from interior_fit.floors.fit_selected_floor import selected

    selected()


def fit_view_room() -> None:
    from interior_fit.fit_from_viewport import run

    run("room")


def fit_view_stair() -> None:
    from interior_fit.fit_from_viewport import run

    run("stair")


def fit_view_floor() -> None:
    from interior_fit.fit_from_viewport import run

    run("floor")


def accept_boundary_review() -> None:
    from interior_fit.rooms.authoring.review_boundary import apply_selected

    apply_selected()

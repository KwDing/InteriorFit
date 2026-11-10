"""Author from the level viewport without selecting or placing an actor."""

import unreal as u

from . import floor_rooms, polygon_editor, room_contour, stair_scan


def run(mode):
    seed = u.InteriorFitLibrary.create_viewport_seed()
    if not seed:
        u.EditorDialog.show_message(
            "Interior Fit", "请退出 Play 或 Simulate，点击关卡的透视视口后重试。", u.AppMsgType.OK
        )
        return

    def release():
        if u.SystemLibrary.is_valid(seed):
            u.get_editor_subsystem(u.EditorActorSubsystem).destroy_actor(seed)

    def failed(reason):
        release()
        u.EditorDialog.show_message("Interior Fit", str(reason), u.AppMsgType.OK)

    def review(result):
        try:
            if mode == "floor":
                floor_rooms.review_result(result)
            else:
                polygon_editor.review_result(seed, result)
        except Exception as error:
            u.log_error(str(error))
            u.EditorDialog.show_message("Interior Fit", str(error), u.AppMsgType.OK)
        finally:
            release()

    try:
        if mode == "floor":
            if floor_rooms.confirm_floor():
                floor_rooms.run(seed, review, failed)
            else:
                release()
        else:
            scanner = stair_scan.scan if mode == "stair" else room_contour.scan
            polygon_editor.start(seed, review, failed, scanner)
    except Exception as error:
        failed(error)

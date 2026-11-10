"""Transactional two-box authoring; remove only unambiguous internal Portal actors."""
import json
import unreal as u
from .. import editor


def _portal_sides(portal):
    """Probe each aperture's centre and corners, in its full 3D orientation."""
    vertices = [v for f in json.loads(u.InteriorFitLibrary.get_volume_faces(portal)) for v in f['vertices']]
    if not vertices:
        return None
    transform = portal.get_actor_transform()
    local = [u.MathLibrary.inverse_transform_location(transform, u.Vector(*v)) for v in vertices]
    lower = [min(v.to_tuple()[axis] for v in local) for axis in range(3)]
    upper = [max(v.to_tuple()[axis] for v in local) for axis in range(3)]
    if min(b-a for a,b in zip(lower, upper)) <= 0:
        return None
    centre = [(a+b)/2 for a,b in zip(lower, upper)]
    half = [(b-a)/2 for a,b in zip(lower, upper)]
    return [[u.MathLibrary.transform_location(transform, u.Vector(
        centre[0]+sign*(half[0]+1), centre[1]+y*half[1], centre[2]+z*half[2]))
        for y,z in ((0,0),(-.95,-.95),(-.95,.95),(.95,-.95),(.95,.95))] for sign in (-1,1)]


def internal_portals(first, second):
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    others = [r for r in editor.room_volumes() if r not in (first,second)]
    inside = u.InteriorFitLibrary.contains_point
    found = []
    for actor in actors.get_all_level_actors():
        if not isinstance(actor,u.AkAcousticPortal) or actor.get_level() != first.get_level():
            continue
        sides = _portal_sides(actor)
        if not sides or any(inside(r,p) for r in others for side in sides for p in side):
            continue  # Do not guess which Room wins in an overlapping hierarchy.
        pair = [next((r for r in (first,second) if all(inside(r,p) for p in side)),None) for side in sides]
        if set(pair) == {first,second}:
            found.append(actor)
    return found


def apply(first, second):
    """Keep merge and Portal removal in one Undo entry; report any deletion failure."""
    if u.get_editor_subsystem(u.UnrealEditorSubsystem).get_game_world():
        raise ValueError('请退出 PIE 后合并 Room。')
    portals = internal_portals(first,second)
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    removed, retained = [], []
    with u.ScopedEditorTransaction('Merge Rooms and remove internal Portals'):
        error = u.InteriorFitLibrary.merge_touching_boxes(first,second)
        if error:
            raise ValueError(error)
        for portal in portals:
            label = portal.get_actor_label()
            portal.modify()
            (removed if actors.destroy_actor(portal) else retained).append(label)
    actors.set_selected_level_actors([first])
    return dict(removed_portals=removed,retained_portals=retained)


def selected():
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    rooms = actors.get_selected_level_actors()
    if len(rooms) != 2 or not all(isinstance(a,u.AkSpatialAudioVolume) for a in rooms):
        u.EditorDialog.show_message('Interior Fit','请选择两个盒形 AkSpatialAudioVolume。',u.AppMsgType.OK)
        return
    first, second = rooms
    count = len(internal_portals(first,second))
    prompt = (f'保留 {first.get_actor_label()} 的设置，将 {second.get_actor_label()} 合入。\n'
              f'简化共面分割，并删除 {count} 个明确连接这两间 Room 的内部 Portal。\n'
              '外围或归属不明确的 Portal 保留，请复查连接。可一次撤销。')
    if u.EditorDialog.show_message('Interior Fit',prompt,u.AppMsgType.YES_NO) != u.AppReturnType.YES:
        return
    try:
        result = apply(first,second)
        if result['retained_portals']:
            raise RuntimeError('Room 已合并，但以下 Portal 删除失败，请手动处理或撤销：'+', '.join(result['retained_portals']))
    except Exception as error:
        u.EditorDialog.show_message('Interior Fit',str(error),u.AppMsgType.OK)

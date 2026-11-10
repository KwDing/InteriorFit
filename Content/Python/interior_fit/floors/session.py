from collections import deque
import json
import math
import time
from pathlib import Path

import unreal as u
from .. import editor, openings, polygon_editor, floor_recovery
from ..opening_core import overlap
from .bounds import brush_bounds, may_overlap, room_at, door_candidate
from .collision import conflicts

MAX_ROOMS = 12
MAX_PROBES = 36


class FloorSession:
    """Own the pending probes and rollback list until all asynchronous fits complete."""

    def __init__(self, seed, done, failed, report_dir=None):
        self.seed = seed
        self.done = done
        self.failed = failed
        self.retried_start = False
        self.world, self.actors, _ = openings.scene()
        self.start = self.seed.get_actor_location().to_tuple()
        known = editor.room_volumes()
        ignored = list(known) + [self.seed]
        self.queue = deque([self.start])
        self.visited = set()
        self.reviewed = []
        self.created = []
        self.skipped = []
        self.comparisons = []
        self.opening_batches = []
        self.folder = Path(report_dir) if report_dir else Path(u.Paths.project_saved_dir()) / "InteriorFit"
        self.probe = None
        self.timings = []
        self.room_started = 0
        first_floor = editor.trace(self.world, self.start, (self.start[0], self.start[1], self.start[2] - 480), ignored)
        if not first_floor:
            raise ValueError("起点下方未测到地板")
        self.floor = first_floor["point"][2]

    def clear_probe(self):
        if self.probe and u.SystemLibrary.is_valid(self.probe):
            self.actors.destroy_actor(self.probe)
        self.probe = None

    def abort(self, error):
        self.clear_probe()
        for room in reversed(self.created):
            if u.SystemLibrary.is_valid(room):
                self.actors.destroy_actor(room)
        self.failed(str(error))

    def visit(self, room):
        if room in self.reviewed:
            return
        self.reviewed.append(room)
        data = openings.discover([room], recognize_doors=True)
        self.opening_batches.append(data)
        for row in data["rows"]:
            if not door_candidate(row) or abs(row["center"][2] - row["half_extent"][2] - self.floor) > 40:
                continue
            angle = math.radians(row["yaw"])
            x, y, z = row["center"]
            for sign in (-1, 1):
                pos = (x + sign * 125 * math.cos(angle), y + sign * 125 * math.sin(angle), self.floor + 110)
                if not room_at([room], pos):
                    self.queue.append(pos)

    def complete(self):
        data = (
            openings.reconnect_discovered(self.opening_batches)
            if self.reviewed
            else dict(world=self.world.get_path_name(), rows=[])
        )
        doors = []
        for row in data["rows"]:
            if door_candidate(row) and not any(
                sorted(row["rooms"]) == sorted(prev["rooms"]) and overlap(row, prev) for prev in doors
            ):
                row["checked"] = not row["blocked"] and "Outdoors" not in row["rooms"]
                doors.append(row)
        data["rows"] = doors
        data.update(
            seed=list(self.start),
            floor_z=self.floor,
            created_rooms=[r.get_actor_label() for r in self.created],
            visited_rooms=[r.get_actor_label() for r in self.reviewed],
            skipped=self.skipped,
            remaining_probes=len(self.queue),
            comparisons=self.comparisons,
            room_times_ms=self.timings,
            stop_reason='room_limit' if len(self.reviewed)>=MAX_ROOMS else 'probe_limit' if len(self.visited)>=MAX_PROBES else 'complete',
        )
        self.folder.mkdir(exist_ok=True, parents=True)
        (self.folder / "floor_rooms.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.done(data)

    def recover(self, reason):
        try:
            if (
                not self.probe
                or not u.SystemLibrary.is_valid(self.probe)
                or not u.SystemLibrary.is_valid(self.seed)
                or self.seed.get_world() != self.world
            ):
                self.abort(reason)
                return
            blocked = [floor_recovery.ProtectedRoom(r, brush_bounds(r)) for r in editor.room_volumes()]
            polygon_editor.start(
                self.probe, self.accepted, self.reject, lambda p: floor_recovery.scan(p, self.floor, blocked),
                protected=editor.room_volumes()
            )
        except Exception as error:
            self.abort(error)

    def reject(self, reason):
        self.skipped.append(
            dict(point=list(self.probe.get_actor_location().to_tuple()) if self.probe else None, reason=str(reason))
        )
        if (
            not self.retried_start
            and not self.reviewed
            and self.probe
            and tuple(self.probe.get_actor_location().to_tuple()) == self.start
        ):
            self.retried_start = True
            for dx, dy in ((85, -45), (-85, 45)):
                alternate = (self.start[0] + dx, self.start[1] + dy, self.start[2])
                if not editor.trace(self.world, self.start, alternate, editor.room_volumes() + [self.probe, self.seed]):
                    self.queue.append(alternate)
        self.clear_probe()
        self.advance()

    def accepted(self, result):
        try:
            pos = self.probe.get_actor_location().to_tuple()
            ground_span = 0
            if result["model"] == "stepped_heightfield":
                levels = [cell[2] for cell in result["height_cells"]]
                ground_span = max(levels) - min(levels)
            if result["model"] == "strip_profile":
                levels = [section[2] for section in result["sections"]]
                ground_span = max(levels) - min(levels)
            if result["model"] in ("stair_layers", "floor_clipped_sphere", "ellipsoid_cap", "ridge_prism") or ground_span > 60:
                self.recover("变高空间，尝试仅本层的采样")
                return
            room = self._create_room(result, pos)
            if room is None:
                if result.get("storey_cells"):
                    self.reject("候选越界或与已有 Room 相交，已跳过")
                else:
                    self.recover("尝试保留已有 Room 的本层区域")
                return
            elapsed = (time.perf_counter()-self.room_started)*1000
            self.timings.append(dict(room=room.get_actor_label(),milliseconds=elapsed,rays=result.get('rays'),review=result.get('preview_required',False)))
            if elapsed>=500:
                self.actors.destroy_actor(room)
                self.created.remove(room)
                self.reject('本房生成超过 500 ms，停止采纳该候选；已完成房间保留')
                return
            self.clear_probe()
            self.visit(room)
            self.advance()
        except Exception as error:
            self.abort(error)

    def _visit_existing(self, room, key, pos):
        """A staircase is an endpoint; only same-storey floor rooms extend the search."""
        lo, _ = brush_bounds(room)[2]
        if room.actor_has_tag("InteriorFitFloorRoom") and abs(lo - self.floor) <= 38:
            self.visit(room)
        elif key == tuple(round(v / 20) for v in self.start):
            self.skipped.append(dict(point=list(pos), reason="起点已在受保护 Room 内，请把种子放到楼层主房间"))

    def advance(self):
        try:
            if openings.scene()[0] != self.world or not u.SystemLibrary.is_valid(self.seed):
                raise ValueError("扫描期间关卡或种子发生变化")
            while self.queue and len(self.visited) < MAX_PROBES and len(self.reviewed) < MAX_ROOMS:
                pos = self.queue.popleft()
                key = tuple(round(v / 20) for v in pos)
                if key in self.visited:
                    continue
                self.visited.add(key)
                rooms = editor.room_volumes()
                existing = room_at(rooms, pos)
                if existing:
                    self._visit_existing(existing, key, pos)
                    continue
                x, y, z = pos
                low = editor.trace(self.world, pos, (x, y, z - 450), rooms)
                high = editor.trace(self.world, pos, (x, y, z + 750), rooms)
                if (
                    not low
                    or not high
                    or abs(low["point"][2] - self.floor) > 38
                    or high["point"][2] - low["point"][2] < 190
                ):
                    continue
                self.probe = self.actors.spawn_actor_from_class(u.TargetPoint, u.Vector(*pos), transient=True)
                self.room_started = time.perf_counter()
                polygon_editor.start(self.probe, self.accepted, self.recover,protected=rooms)
                return
            self.complete()
        except Exception as error:
            self.abort(error)

    def _create_room(self, result, pos):
        with u.ScopedEditorTransaction("Fit one room on floor"):
            prefix = "InteriorFit_Floor_" + self.seed.get_actor_label() + "_"
            used = {v.get_actor_label() for v in editor.room_volumes()}
            number = len(self.created) + 1
            while prefix + str(number) in used:
                number += 1
            label = prefix + str(number)
            # Floor authoring explicitly reviews the completed batch. Validate the
            # same final mesh used by single-room Preview before authoring it.
            from ..rooms.brush import prepare_room
            prepared = prepare_room(result)
            room = polygon_editor.create_room(self.world, result, label,prepared=prepared)
            # The brush exists in the world from this point. Take ownership before any query can fail.
            self.created.append(room)
            nearby = [r for r in editor.room_volumes() if r != room and may_overlap(room, r)]
            conflict, checks = conflicts(room,nearby,result)
            self.comparisons.append(dict(candidate=label,point=list(pos),collision=checks,conflict=conflict))
            conflict = conflict or not room_at([room], pos)
            if conflict:
                if not self.actors.destroy_actor(room):
                    raise RuntimeError("无法清理冲突的 Room：" + label)
                self.created.remove(room)
            else:
                editor.configure_wwise_room(room)
                room.set_editor_property("tags", list(room.tags) + [u.Name("InteriorFitFloorRoom")])
                room.set_folder_path("InteriorFit/Floor Rooms")
        return None if conflict else room


"""Human-readable review text for ordinary room fits."""

import unreal as u


def build(world, result, points):
    message = f"{result['columns']} 个连通网格，{len(points)} 个顶点。"
    if result["model"] in ("ellipsoid_cap", "ridge_prism"):
        message = (
            "曲顶或双坡顶轮廓已通过独立探针验证。\n"
            f"候选包含 {len(result['triangles'])} 个三角形。"
        )
        if "wall_min_cm" in result:
            message = (
                f"采样最薄墙厚 {result['wall_min_cm']:.1f} cm。\n"
                f"厚墙候选包含 {len(result['triangles'])} 个三角形。"
            )
        elif result.get("wall_profile_review"):
            message = result["wall_profile_review"] + "\n" + message
        elif "triangle_budget" in result:
            message = (
                f"曲顶已简化为 {result['triangle_budget']} 个三角形。\n"
                "请审核檐口、墙角和门边的室内外归属。"
            )
    if result["model"] == "strip_profile":
        message = (
            f"检测到 {len(result['sections'])} 个连续高度区段。\n"
            "请在侧视图核对台阶或顶高分界。"
        )
    if result["model"] == "wall_plane_prism":
        if result.get("curved_walls"):
            message = (
                f"曲墙以 {len(points)} 段折线近似，已抽查墙面、地板和顶板。\n"
                "请核对曲线处的贴合度。"
            )
        else:
            message = (
                f"已验证室内地板、顶板及 {len(points)} 段直墙。\n请核对凹口。"
            )
    if result["model"] == "floor_clipped_sphere":
        message = (
            f"球形候选半径 {result['radius']:.1f} cm，底部沿地板裁切。\n"
            "请核对曲面与地板相交的位置。"
        )
    if result["model"] == "circular_prism":
        hints = result.get("opening_hints", [])
        for location in hints:
            p = u.Vector(*location)
            u.SystemLibrary.draw_debug_line(
                world,
                p - u.Vector(0, 0, 30),
                p + u.Vector(0, 0, 30),
                u.LinearColor(1, 0.5, 0, 1),
                12,
                4,
            )
        message = (
            f"圆柱截面 {len(points)} 边，已抽查地板和顶板。\n"
            f"橙线标出 {len(hints)} 个疑似开口方向。"
        )
    if result["model"] == "stair_layers":
        levels = result.get("connected_landing_heights_cm", [])
        status = (
            f"沿踏步连通两个平台：Z {levels[0]} → {levels[1]} cm。"
            if levels
            else "仅找到局部梯段，尚未确认两个楼层平台。"
        )
        message = (
            f"{status}\n"
            f"已排除 {result['excluded_flat_states']} 个外围空气区间。\n"
            "请核对楼梯间边界。"
        )
    return message + "\n\n创建 Wwise Room？"

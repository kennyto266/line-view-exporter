# LineViewExporter_Blender.py
# ---------------------------
# Blender addon - exports orthographic line views (Front / Back / Left /
# Right / Top / Bottom) of selected mesh objects to an SVG sheet that Adobe
# Illustrator opens as fully editable vector paths.
#
# Same algorithm and output format as the 3ds Max "LineViewExporter.ms" in
# this repository, for users who are not on Windows (3ds Max has no macOS
# build; Blender is free and runs natively on macOS / Windows / Linux).
#
# Install:
#   Edit > Preferences > Add-ons > Install (or "Install from Disk" in 4.2+)
#   -> pick this .py file -> enable "Import-Export: Line View Exporter".
# Use:
#   Select objects (no selection = all visible meshes) ->
#   View3D > Sidebar (N) > "Line View" tab > "Export Line Views SVG".

bl_info = {
    "name": "Line View Exporter (SVG for Illustrator)",
    "author": "kennyto266",
    "version": (1, 7, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar (N key) > Line View",
    "description": "Export Front/Right/Top orthographic line views of meshes "
                   "as an editable SVG blueprint for Adobe Illustrator",
    "category": "Import-Export",
}

import bpy
import bmesh
import math
import time
from mathutils import Vector
from bpy.props import BoolProperty, FloatProperty, IntProperty, EnumProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper

# name, right, down, viewDir, sheet grid col/row.
# Projections match Blender's own ortho views
# (Front: +X right / +Z up, Top: +X right / +Y down), same as the 3ds Max tool.
_VIEWS = [
    ("FRONT",  ( 1.0, 0.0, 0.0), ( 0.0, 0.0, -1.0), ( 0.0,  1.0, 0.0),  0, 1),
    ("BACK",   (-1.0, 0.0, 0.0), ( 0.0, 0.0, -1.0), ( 0.0, -1.0, 0.0),  2, 1),
    ("RIGHT",  ( 0.0, 1.0, 0.0), ( 0.0, 0.0, -1.0), (-1.0,  0.0, 0.0),  1, 1),
    ("LEFT",   ( 0.0, -1.0, 0.0), ( 0.0, 0.0, -1.0), ( 1.0,  0.0, 0.0), -1, 1),
    ("TOP",    ( 1.0, 0.0, 0.0), ( 0.0, 1.0,  0.0), ( 0.0,  0.0, -1.0),  0, 0),
    ("BOTTOM", ( 1.0, 0.0, 0.0), ( 0.0, -1.0, 0.0), ( 0.0,  0.0,  1.0),  0, 2),
]


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def _build_world_data(obj, depsgraph):
    """Return (world_verts, face_normals, [(edge_verts, edge_faces), ...])."""
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    mw = obj_eval.matrix_world

    wverts = [mw @ v.co for v in bm.verts]

    facen = []
    for f in bm.faces:
        vs = f.verts
        a = wverts[vs[0].index]
        b = wverts[vs[1].index]
        c = wverts[vs[2].index]
        n = (b - a).cross(c - a)
        try:
            n.normalize()
        except ValueError:  # degenerate face
            n = Vector((0.0, 0.0, 1.0))
        facen.append(n)

    edges = []
    for e in bm.edges:
        ev = (e.verts[0].index, e.verts[1].index)
        ef = tuple(f.index for f in e.link_faces)
        edges.append((ev, ef))

    bm.free()
    obj_eval.to_mesh_clear()
    return wverts, facen, edges


def _seg_bounds(items):
    x0 = y0 = 1.0e30
    x1 = y1 = -1.0e30
    for _name, segs in items:
        for (ax, ay), (bx, by) in segs:
            x0 = min(x0, ax, bx)
            y0 = min(y0, ay, by)
            x1 = max(x1, ax, bx)
            y1 = max(y1, ay, by)
    return x0, y0, x1, y1



def _unit_info(unit_label, scene):
    """Return (factor, label): scene units * factor = value in the label unit.
    "units"/empty -> auto label from the scene unit settings (1:1);
    "mm"/"cm"/"m" -> convert from the scene unit."""
    us = getattr(scene, "unit_settings", None)
    sysname = "units"
    mm_per = 1.0
    if us is not None:
        if us.system == 'METRIC':
            mm_per = us.scale_length * 1000.0
            if abs(mm_per - 1.0) < 1e-6:
                sysname = "mm"
            elif abs(mm_per - 10.0) < 1e-6:
                sysname = "cm"
            else:
                sysname = "m"
        elif us.system == 'IMPERIAL':
            mm_per = us.scale_length * 304.8
            sysname = "in"
    u = (unit_label or "").lower()
    if u == "mm":
        return mm_per, "mm"
    if u == "cm":
        return mm_per / 10.0, "cm"
    if u == "m":
        return mm_per / 1000.0, "m"
    return 1.0, sysname



class LINEVIEW_OT_export_svg(Operator, ExportHelper):
    """Export Front/Right/Top line views of selected meshes as an editable SVG blueprint for Adobe Illustrator"""
    bl_idname = "export.lineview_svg"
    bl_label = "Export Line Views SVG"
    bl_options = {'REGISTER'}

    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(
        default="*.svg", options={'HIDDEN'}, maxlen=255)

    view_front: BoolProperty(name="Front", default=True)
    view_back: BoolProperty(name="Back", default=False)
    view_right: BoolProperty(name="Right", default=True)
    view_left: BoolProperty(name="Left", default=False)
    view_top: BoolProperty(name="Top", default=True)
    view_bottom: BoolProperty(name="Bottom", default=False)

    crease_angle: IntProperty(
        name="Crease Angle",
        description="An edge shared by two faces is drawn only when the faces "
                    "bend more than this angle (higher = cleaner, fewer lines)",
        default=30, min=0, max=90)
    stroke_weight: FloatProperty(
        name="Stroke Weight (pt)",
        description="Line weight in Illustrator",
        default=0.5, min=0.05, max=5.0)
    include_hidden: BoolProperty(
        name="Hidden Edges (dashed)",
        description="Draw back-facing outlines/creases as grey dashed lines",
        default=False)
    flip_facing: BoolProperty(
        name="Flip Facing",
        description="Use if the output looks inside-out (flipped normals)",
        default=False)
    page_mode: EnumProperty(
        name="Sheet",
        items=[
            ('A4L', "A4 Landscape (fit)", "Auto-fit all views to an A4 landscape sheet"),
            ('A3L', "A3 Landscape (fit)", "Auto-fit all views to an A3 landscape sheet"),
            ('A4P', "A4 Portrait (fit)", "Auto-fit all views to an A4 portrait sheet"),
            ('NONE', "No Fit (1:1)", "1 scene unit = 1 pt, true-size output"),
        ],
        default='A4L')
    min_pt: FloatProperty(
        name="Drop Lines Shorter (pt)",
        description="Skip segments smaller than this on the sheet (kills sub-pixel speckle)",
        default=0.4, min=0.0, max=5.0)
    draw_open: BoolProperty(
        name="Open (Border) Edges",
        description="Draw open/border edges; uncheck if a broken mesh floods the sheet",
        default=True)
    use_dims: BoolProperty(
        name="Dimension Annotations",
        description="Add engineering-style dimension lines (view width/height) with arrows and labels",
        default=True)
    unit_label: StringProperty(
        name="Unit Label",
        description="Text appended to dimension numbers, e.g. mm, cm, units",
        default="units", maxlen=16)
    outline_only: BoolProperty(
        name="Outline Only",
        description="Draw silhouettes and border edges only, no crease lines - "
                    "round things come out as clean circle outlines",
        default=False)
    max_segs: IntProperty(
        name="Max Lines Per Object",
        description="Per-object cap on written segments, keeping the longest ones "
                    "(0 = unlimited). Tames dense machinery/lattice clusters.",
        default=0, min=0, max=100000)
    separate_segs: BoolProperty(
        name="Every Line = Own Path",
        description="Emit each line as its own path so every line can be selected, "
                    "moved and stretched individually in Illustrator/Inkscape",
        default=True)
    size_labels: BoolProperty(
        name="Size Label Per Object",
        description="Label every object with its W x H size (in the dimension unit); "
                    "the label travels with the piece",
        default=True)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False

        box = layout.box()
        box.label(text="Views")
        row = box.row()
        row.prop(self, "view_front")
        row.prop(self, "view_right")
        row.prop(self, "view_top")
        row = box.row()
        row.prop(self, "view_back")
        row.prop(self, "view_left")
        row.prop(self, "view_bottom")

        box = layout.box()
        box.label(text="Line Extraction")
        box.prop(self, "crease_angle")
        box.prop(self, "stroke_weight")
        box.prop(self, "min_pt")
        box.prop(self, "draw_open")
        box.prop(self, "include_hidden")
        box.prop(self, "flip_facing")

        box = layout.box()
        box.label(text="Dimensions")
        box.prop(self, "use_dims")
        box.prop(self, "unit_label")
        box.prop(self, "outline_only")
        box.prop(self, "max_segs")
        box.prop(self, "separate_segs")
        box.prop(self, "size_labels")

        box = layout.box()
        box.label(text="Sheet")
        box.prop(self, "page_mode")

    def execute(self, context):
        t0 = time.time()
        depsgraph = context.evaluated_depsgraph_get()

        objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not objs:
            objs = [o for o in context.scene.objects
                    if o.type == 'MESH' and o.visible_get()]
        if not objs:
            self.report({'WARNING'}, "No mesh objects to export")
            return {'CANCELLED'}

        flags = {
            'FRONT': self.view_front, 'BACK': self.view_back,
            'RIGHT': self.view_right, 'LEFT': self.view_left,
            'TOP': self.view_top, 'BOTTOM': self.view_bottom,
        }
        views = []
        for name, r, d, vd, col, row in _VIEWS:
            if flags[name]:
                views.append({
                    'name': name,
                    'right': Vector(r), 'down': Vector(d), 'dir': Vector(vd),
                    'col': col, 'row': row,
                    'vis': [], 'hid': [], 'bb': (0.0, 0.0, 0.0, 0.0),
                    'sc': 1.0, 'ox': 0.0, 'oy': 0.0,
                })
        if not views:
            self.report({'WARNING'}, "Enable at least one view")
            return {'CANCELLED'}

        crease_rad = math.radians(self.crease_angle)
        fc = -1.0 if self.flip_facing else 1.0
        skipped = []

        for obj in objs:
            try:
                wverts, facen, edges = _build_world_data(obj, depsgraph)
            except Exception:
                skipped.append(obj.name)
                continue

            for v in views:
                vs_segs = []
                hs_segs = []
                for ev, ef in edges:
                    if not ef:
                        continue
                    n1 = facen[ef[0]]
                    c1 = (fc * n1.dot(v['dir'])) < 0.0
                    c2 = ((fc * facen[ef[1]].dot(v['dir'])) < 0.0
                          if len(ef) > 1 else False)
                    vis_e = False
                    hid_e = False
                    if len(ef) == 1:
                        if self.draw_open:
                            vis_e = c1
                            if self.include_hidden:
                                hid_e = not c1
                    else:
                        if c1 != c2:
                            vis_e = True  # silhouette
                        elif c1 and not self.outline_only:  # both facing: crease test
                            dp = max(-1.0, min(1.0, n1.dot(facen[ef[1]])))
                            vis_e = math.acos(dp) > crease_rad
                        elif self.include_hidden and not self.outline_only:  # both back-facing
                            dp = max(-1.0, min(1.0, n1.dot(facen[ef[1]])))
                            hid_e = math.acos(dp) > crease_rad
                    if vis_e or hid_e:
                        p1 = wverts[ev[0]]
                        p2 = wverts[ev[1]]
                        s1 = (p1.dot(v['right']), p1.dot(v['down']))
                        s2 = (p2.dot(v['right']), p2.dot(v['down']))
                        if vis_e:
                            vs_segs.append((s1, s2))
                        if hid_e:
                            hs_segs.append((s1, s2))
                v['vis'].append((obj.name, vs_segs))
                if self.include_hidden:
                    v['hid'].append((obj.name, hs_segs))

        # bounding boxes
        for v in views:
            items = list(v['vis'])
            if self.include_hidden:
                items += list(v['hid'])
            if any(segs for _n, segs in items):
                v['bb'] = _seg_bounds(items)

        # sheet layout (third-angle style grid), same maths as the Max tool
        m = 24.0
        gap = 20.0
        pad = 8.0
        label_h = 16.0
        col_min = min(v['col'] for v in views)
        col_max = max(v['col'] for v in views)
        row_min = min(v['row'] for v in views)
        row_max = max(v['row'] for v in views)
        ncols = col_max - col_min + 1
        nrows = row_max - row_min + 1

        if self.page_mode == 'NONE':
            maxw = max(1.0e-6, max(v['bb'][2] - v['bb'][0] for v in views))
            maxh = max(1.0e-6, max(v['bb'][3] - v['bb'][1] for v in views))
            cellw = maxw + 2 * pad
            cellh = maxh + 2 * pad + label_h
            pagew = 2 * m + ncols * cellw + (ncols - 1) * gap
            pageh = 2 * m + nrows * cellh + (nrows - 1) * gap
            sc = 1.0
        else:
            pagew, pageh = {
                'A4L': (842.0, 595.0),
                'A3L': (1191.0, 842.0),
                'A4P': (595.0, 842.0),
            }[self.page_mode]
            cellw = (pagew - 2 * m - (ncols - 1) * gap) / ncols
            cellh = (pageh - 2 * m - (nrows - 1) * gap) / nrows
            sc = 1.0e30
            for v in views:
                w = max(1.0e-6, v['bb'][2] - v['bb'][0])
                h = max(1.0e-6, v['bb'][3] - v['bb'][1])
                sc = min(sc, min((cellw - 2 * pad) / w,
                                 (cellh - 2 * pad - label_h) / h))

        for v in views:
            w = (v['bb'][2] - v['bb'][0]) * sc
            h = (v['bb'][3] - v['bb'][1]) * sc
            cx = m + (v['col'] - col_min) * (cellw + gap)
            cy = m + (v['row'] - row_min) * (cellh + gap)
            v['sc'] = sc
            v['ox'] = cx + (cellw - w) / 2.0 - v['bb'][0] * sc
            v['oy'] = cy + (cellh - label_h - h) / 2.0 - v['bb'][1] * sc

        # write SVG
        out = []
        out.append("<?xml version='1.0' encoding='UTF-8'?>\n")
        out.append(
            "<svg xmlns='http://www.w3.org/2000/svg' width='%.3f' height='%.3f' "
            "viewBox='0 0 %.3f %.3f'>\n" % (pagew, pageh, pagew, pageh))

        def _paths(entries):
            for nm, segs in entries:
                if not segs:
                    continue
                useg = segs
                if self.max_segs > 0 and len(segs) > self.max_segs:
                    useg = sorted(
                        segs,
                        key=lambda s: (s[1][0] - s[0][0]) ** 2 + (s[1][1] - s[0][1]) ** 2,
                        reverse=True)[:self.max_segs]
                filt = []
                for (x1, y1), (x2, y2) in useg:
                    if self.min_pt > 0.0:
                        if math.hypot((x2 - x1) * sc, (y2 - y1) * sc) < self.min_pt:
                            continue
                    filt.append((x1, y1, x2, y2))
                if not filt:
                    continue
                uifac_l, _uilab = _unit_info(self.unit_label, context.scene)
                if self.separate_segs:
                    out.append("<g id='%s'>\n" % _xml_escape(nm))
                    xs0 = min(f[0] for f in filt); xs1 = max(f[2] for f in filt)
                    ys0 = min(f[1] for f in filt); ys1 = max(f[3] for f in filt)
                    for i, (x1, y1, x2, y2) in enumerate(filt, 1):
                        out.append(
                            "<path id='%s_%d' d='M%.3f %.3f L%.3f %.3f'/>\n"
                            % (_xml_escape(nm), i,
                               x1 * sc + ox, y1 * sc + oy,
                               x2 * sc + ox, y2 * sc + oy))
                    if self.size_labels and ((xs1 - xs0) >= 6.0 or (ys1 - ys0) >= 6.0):
                        out.append(
                            "<text x='%.3f' y='%.3f' font-family='Arial' font-size='5.5' fill='#888888'>%.1f x %.1f</text>\n"
                            % (xs0, ys0 - 1.5,
                               (xs1 - xs0) / (sc * uifac_l), (ys1 - ys0) / (sc * uifac_l)))
                    out.append("</g>\n")
                else:
                    out.append("<path id='%s' d='" % _xml_escape(nm))
                    for x1, y1, x2, y2 in filt:
                        out.append("M%.3f %.3f L%.3f %.3f " % (
                            x1 * sc + ox, y1 * sc + oy,
                            x2 * sc + ox, y2 * sc + oy))
                    out.append("'/>\n")
                    if self.size_labels:
                        xs0 = min(f[0] for f in filt); xs1 = max(f[2] for f in filt)
                        ys0 = min(f[1] for f in filt); ys1 = max(f[3] for f in filt)
                        if (xs1 - xs0) >= 6.0 or (ys1 - ys0) >= 6.0:
                            out.append(
                                "<text x='%.3f' y='%.3f' font-family='Arial' font-size='5.5' fill='#888888'>%.1f x %.1f</text>\n"
                                % (xs0, ys0 - 1.5,
                                   (xs1 - xs0) / (sc * uifac_l), (ys1 - ys0) / (sc * uifac_l)))

        for v in views:
            sc = v['sc']
            ox = v['ox']
            oy = v['oy']
            out.append(
                "<g id='%s' fill='none' stroke='#000000' stroke-width='%.3f' "
                "stroke-linecap='round' stroke-linejoin='round'>\n"
                % (v['name'], self.stroke_weight))
            _paths(v['vis'])
            out.append("</g>\n")
            if self.include_hidden:
                out.append(
                    "<g id='%s_hidden' fill='none' stroke='#999999' "
                    "stroke-width='%.3f' stroke-dasharray='3,2' "
                    "stroke-linecap='round'>\n"
                    % (v['name'], self.stroke_weight * 0.7))
                _paths([(nm + "_hid", segs) for nm, segs in v['hid']])
                out.append("</g>\n")
            lx = m + (v['col'] - col_min) * (cellw + gap) + cellw / 2.0
            ly = m + (v['row'] - row_min) * (cellh + gap) + cellh - 5.0
            out.append(
                "<text x='%.3f' y='%.3f' font-family='Arial' font-size='9' "
                "text-anchor='middle' fill='#000000'>%s</text>\n"
                % (lx, ly, v['name']))

            # engineering-style dimensions for this view (width below, height left)
            if self.use_dims:
                x0 = v['bb'][0] * sc + ox
                x1 = v['bb'][2] * sc + ox
                y0 = v['bb'][1] * sc + oy
                y1 = v['bb'][3] * sc + oy
                dimcol = '#555555'
                uifac, uilab = _unit_info(self.unit_label, context.scene)
                ulab = _xml_escape(uilab)
                wu = (v['bb'][2] - v['bb'][0]) * uifac
                hu = (v['bb'][3] - v['bb'][1]) * uifac

                def _arrow(tx, ty, ux, uy):
                    bx2 = tx - ux * 7.0
                    by2 = ty - uy * 7.0
                    px2 = -uy * 2.2
                    py2 = ux * 2.2
                    out.append(
                        "<path d='M%.3f %.3f L%.3f %.3f L%.3f %.3f Z' fill='%s'/>\n"
                        % (tx, ty, bx2 + px2, by2 + py2, bx2 - px2, by2 - py2, dimcol))

                if x1 - x0 > 26.0:
                    dly = y0 - 12.0
                    out.append("<g id='%s_dimW' stroke='%s' stroke-width='0.3' fill='none'>\n"
                               % (v['name'], dimcol))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (x0, y0 + 1.5, x0, dly - 2.0))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (x1, y0 + 1.5, x1, dly - 2.0))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (x0, dly, x1, dly))
                    out.append("</g>\n")
                    _arrow(x0, dly, -1.0, 0.0)
                    _arrow(x1, dly, 1.0, 0.0)
                    out.append(
                        "<text x='%.3f' y='%.3f' font-family='Arial' font-size='7' "
                        "text-anchor='middle' fill='%s'>%.1f %s</text>\n"
                        % ((x0 + x1) / 2.0, dly - 3.0, dimcol, wu, ulab))
                if y1 - y0 > 26.0:
                    dlx = x0 - 12.0
                    out.append("<g id='%s_dimH' stroke='%s' stroke-width='0.3' fill='none'>\n"
                               % (v['name'], dimcol))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (x0 - 1.5, y0, dlx - 2.0, y0))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (x0 - 1.5, y1, dlx - 2.0, y1))
                    out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                               % (dlx, y0, dlx, y1))
                    out.append("</g>\n")
                    _arrow(dlx, y0, 0.0, -1.0)
                    _arrow(dlx, y1, 0.0, 1.0)
                    out.append(
                        "<text x='%.3f' y='%.3f' transform='rotate(-90 %.3f %.3f)' "
                        "font-family='Arial' font-size='7' text-anchor='middle' "
                        "fill='%s'>%.1f %s</text>\n"
                        % (dlx - 3.0, (y0 + y1) / 2.0, dlx - 3.0, (y0 + y1) / 2.0,
                           dimcol, hu, ulab))

        # scale bar (in target units)
        uifac, uilab = _unit_info(self.unit_label, context.scene)
        eff_pt = sc * uifac
        nice_l = 1.0
        for k in range(-6, 7):
            for b in (1.0, 2.0, 5.0):
                L = b * (10.0 ** k)
                if 40.0 <= L * eff_pt <= 160.0:
                    nice_l = L
        bar_px = nice_l * eff_pt
        if bar_px <= pagew - 2 * m:
            bx = pagew - m - bar_px
            by = pageh - 10.0
            out.append("<g id='scale_bar' stroke='#000000' stroke-width='0.5'>\n")
            out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                       % (bx, by, bx + bar_px, by))
            out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                       % (bx, by - 3.0, bx, by + 3.0))
            out.append("<line x1='%.3f' y1='%.3f' x2='%.3f' y2='%.3f'/>\n"
                       % (bx + bar_px, by - 3.0, bx + bar_px, by + 3.0))
            out.append("</g>\n")
            out.append(
                "<text x='%.3f' y='%.3f' font-family='Arial' font-size='8' "
                "text-anchor='middle' fill='#000000'>%g %s</text>\n"
                % (bx + bar_px / 2.0, by - 5.0, nice_l, uilab))

        out.append("</svg>\n")

        try:
            with open(self.filepath, 'w', encoding='utf-8') as fh:
                fh.write(''.join(out))
        except OSError as ex:
            self.report({'ERROR'}, "Cannot write file: %s" % ex)
            return {'CANCELLED'}

        msg = "Exported %s in %.1fs" % (self.filepath, time.time() - t0)
        if skipped:
            msg += " (skipped: %s)" % ", ".join(skipped)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class LINEVIEW_PT_main(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Line View"
    bl_label = "Line View -> SVG"
    bl_idname = "LINEVIEW_PT_main"

    def draw(self, context):
        self.layout.operator("export.lineview_svg", icon='EXPORT')


classes = (LINEVIEW_OT_export_svg, LINEVIEW_PT_main)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()

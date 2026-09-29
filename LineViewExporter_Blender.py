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
    "version": (1, 0, 0),
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
        box.prop(self, "include_hidden")
        box.prop(self, "flip_facing")

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
                        vis_e = c1
                        if self.include_hidden:
                            hid_e = not c1
                    else:
                        if c1 != c2:
                            vis_e = True  # silhouette
                        elif c1:  # both facing: crease test
                            dp = max(-1.0, min(1.0, n1.dot(facen[ef[1]])))
                            vis_e = math.acos(dp) > crease_rad
                        elif self.include_hidden:  # both back-facing
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
                out.append("<path id='%s' d='" % _xml_escape(nm))
                for (x1, y1), (x2, y2) in segs:
                    out.append("M%.3f %.3f L%.3f %.3f " % (
                        x1 * sc + ox, y1 * sc + oy,
                        x2 * sc + ox, y2 * sc + oy))
                out.append("'/>\n")

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

        # scale bar
        nice_l = 1.0
        for k in range(-6, 7):
            for b in (1.0, 2.0, 5.0):
                L = b * (10.0 ** k)
                if 40.0 <= L * sc <= 160.0:
                    nice_l = L
        bar_px = nice_l * sc
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
                "text-anchor='middle' fill='#000000'>%g units</text>\n"
                % (bx + bar_px / 2.0, by - 5.0, nice_l))

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

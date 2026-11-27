# Builds the sf_set_* ruin pieces from the Sketchfab "Desert Ruins Set Pieces" (CC-BY, Peter Andre) and
# exports them to assets/models/ (re-runnable):
#   blender --background --python blender/scripts/build_sf_set.py [-- <thumbnail dir>]
# The source is one tiny diorama (0.33 x 0.47 m) whose meshes are split per material, not per piece.
# So: put the UV set each material really textures with into layer 0, join everything except the sand,
# sea and palms, weld, then cut each output out as the welded islands whose bbox centre lies in a box.
# One scale for all outputs (x200: a yard pillar ~6.3 m). Each output gets base-colour-only materials,
# origin bottom centre, Y-up GLB with embedded JPEG; the exported file is re-imported, checked and
# (if a thumbnail dir is given) rendered with Workbench.
import bpy, bmesh, math, os, sys
import numpy as np
from mathutils import Vector, Matrix

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_desert_ruins_set.glb")
OUT = os.path.join(P, "assets", "models")
THUMBS = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv[:-1] else None
SCALE = 200.0
BUDGET = 40000
DROP = ("Sand_Ground", "Sea", "Palm_tree")          # ground plane, water plane, alpha-leaf palms
CAMP = (0.010, 0.052, -0.030, 0.004, -1, 0.0095)      # tent, rugs and pots in the front yard (not architecture)
INF = 1.0

OUTPUTS = [
    # name, keep islands whose bbox centre is in this box (x0,x1,y0,y1,z0,z1 source units), exclude box, mode
    ("sf_set_palace",       (-INF, INF, -0.0085, INF, -INF, INF), CAMP, "ground"),   # whole citadel, no yard
    ("sf_set_fallen_tower", (-0.12, -0.06, -0.065, -0.004, -INF, INF), None, "cut"),  # toppled dome tower
    ("sf_set_arcade",       (-0.032, -0.008, 0.115, 0.225, -INF, 0.045), None, "ground"),  # 5-arch screen wall
    ("sf_set_arch",         (0.09, 0.125, -0.06, -0.028, -INF, INF), None, "upright"),  # fallen arch, stood up
]


def base_color_image(mat):
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    link = bsdf.inputs["Base Color"].links[0]
    node = link.from_node
    uv = None
    vec = node.inputs["Vector"].links
    if vec and vec[0].from_node.type == "UVMAP":
        uv = vec[0].from_node.uv_map
    return node.image, uv


def prepare_source():
    """Import, fix UVs, give one material per base-colour image, join and weld. Returns the object."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    bpy.context.view_layer.update()
    mats = {}                                          # image -> new base-colour-only material
    meshes = []
    for o in [o for o in bpy.data.objects if o.type == "MESH"]:
        if any(k in o.name for k in DROP):
            continue
        me = o.data
        img, uvname = base_color_image(me.materials[0])
        uvname = uvname or me.uv_layers[0].name
        if uvname != me.uv_layers[0].name:             # the trim sheets texture with the 2nd UV set
            buf = np.empty(len(me.loops) * 2, np.float32)
            me.uv_layers[uvname].data.foreach_get("uv", buf)
            me.uv_layers[0].data.foreach_set("uv", buf)
        while len(me.uv_layers) > 1:
            me.uv_layers.remove(me.uv_layers[-1])
        if img not in mats:
            if max(img.size) > 2048:
                img.scale(2048, 2048)
            m = bpy.data.materials.new("sf_set_" + ("floor" if "Floor" in o.name else "trim"))
            m.use_nodes = True
            nt = m.node_tree
            bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf.inputs["Roughness"].default_value = 0.95
            tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            mats[img] = m
        me.materials.clear(); me.materials.append(mats[img])
        meshes.append(o)
    for o in meshes:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
    for o in list(bpy.data.objects):
        if o not in meshes:
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()                              # join merges equal materials by data-block
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new(); bm.from_mesh(obj.data)
    # glTF splits vertices on UV seams; weld so islands are real pieces (UVs live on loops, so they survive)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5)
    bm.to_mesh(obj.data); bm.free()
    return obj


def islands(bm):
    seen, out = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, fs = [f], []
        seen.add(f)
        while stack:
            g = stack.pop(); fs.append(g)
            for v in g.verts:
                for h in v.link_faces:
                    if h not in seen:
                        seen.add(h); stack.append(h)
        out.append(fs)
    return out


def inside(c, b):
    return b is not None and b[0] < c.x < b[1] and b[2] < c.y < b[3] and b[4] < c.z < b[5]


def upright_matrix(co):
    """Rotation that stands a lying arch up: long axis -> Z (legs down), width -> Y, thickness -> X."""
    c = co - co.mean(0)
    _, vec = np.linalg.eigh(np.cov(c.T))              # ascending variance
    thick, width, height = vec[:, 0], vec[:, 1], vec[:, 2]
    t, w = c @ height, c @ width
    wmid = (w.min() + w.max()) / 2
    span = t.max() - t.min()
    gap_hi = np.abs(w[t > t.max() - 0.15 * span] - wmid).min()
    gap_lo = np.abs(w[t < t.min() + 0.15 * span] - wmid).min()
    if gap_hi > gap_lo:                                # the legs (gap in the middle) must point down
        height = -height
    R = np.array([thick, width, height])
    if np.linalg.det(R) < 0:
        R[1] = -R[1]
    return Matrix(R.tolist()).to_4x4()


def build(base, name, keep, drop, mode):
    obj = base.copy(); obj.data = base.data.copy(); obj.name = obj.data.name = name
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new(); bm.from_mesh(obj.data)
    kill, overhang = [], []
    for fs in islands(bm):
        vs = [v.co for f in fs for v in f.verts]
        lo = Vector([min(v[k] for v in vs) for k in range(3)])
        c = (lo + Vector([max(v[k] for v in vs) for k in range(3)])) / 2
        if not inside(c, keep) or inside(c, drop):
            kill += fs
        elif lo.y < keep[2]:
            overhang += fs
    if name == "sf_set_palace":   # yard walkway / fence welded to the citadel: cut them just in front of the wall
        geom = list({v for f in overhang for v in f.verts}) + list({e for f in overhang for e in f.edges}) + overhang
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, -0.0003, 0), plane_no=(0, 1, 0), clear_inner=True)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    if mode == "cut":                                  # the tower is half buried: cut it at the source ground
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, 0), plane_no=(0, 0, 1), clear_inner=True)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data); bm.free()
    me = obj.data
    co = np.array([v.co[:] for v in me.vertices])
    if mode == "upright":
        me.transform(upright_matrix(co))
        co = np.array([v.co[:] for v in me.vertices])
    lo, hi = co.min(0), co.max(0)
    # "ground": y=0 is the source ground plane (pieces have small skirts below it); else lowest point
    floor = 0.0 if mode in ("ground", "cut") else lo[2]
    me.transform(Matrix.Scale(SCALE, 4) @ Matrix.Translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -floor)))
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(35))    # hard edges on the masonry, smooth domes
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    if tris > BUDGET:
        # collapse only the small dense islands (finial balls, specks): a global collapse smears the trim UVs
        dup = obj.copy(); dup.data = me.copy(); bpy.context.scene.collection.objects.link(dup)
        for o, want in ((obj, False), (dup, True)):
            bm = bmesh.new(); bm.from_mesh(o.data)
            dense = set()
            for fs in islands(bm):
                vs = [v.co for f in fs for v in f.verts]
                if len(fs) > 60 and max(max(v[k] for v in vs) - min(v[k] for v in vs) for k in range(3)) < 2.0:
                    dense.update(fs)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if (f in dense) != want], context="FACES")
            bm.to_mesh(o.data); bm.free()
        dtris = sum(len(p.vertices) - 2 for p in dup.data.polygons)
        mod = dup.modifiers.new("Decimate", "DECIMATE")
        mod.ratio = max(0.15, (dtris - (tris - BUDGET)) / dtris * 0.97)
        bpy.context.view_layer.objects.active = dup
        bpy.ops.object.modifier_apply(modifier="Decimate")
        bpy.ops.object.select_all(action="DESELECT")
        dup.select_set(True); obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        me = obj.data
    # drop material slots this piece does not use
    used = sorted({p.material_index for p in me.polygons})
    keepm = [me.materials[i] for i in used]
    idx = [used.index(p.material_index) for p in me.polygons]
    me.materials.clear()                               # (clear() also zeroes the polygon indices)
    for m in keepm:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", idx)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    path = os.path.join(OUT, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, use_selection=True,
                              export_image_format="JPEG", export_jpeg_quality=90, export_vertex_color="NONE",
                              export_tangents=False, export_cameras=False, export_lights=False)
    bpy.data.objects.remove(obj)
    return path, tris


def check_and_thumb(path, name):
    for o in list(bpy.data.objects):
        o.hide_render = True
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    ms = [o for o in new if o.type == "MESH"]
    assert len(ms) == 1, (name, len(ms))
    o = ms[0]; me = o.data
    bpy.context.view_layer.update()
    co = [o.matrix_world @ v.co for v in me.vertices]
    lo = Vector([min(v[k] for v in co) for k in range(3)]); hi = Vector([max(v[k] for v in co) for k in range(3)])
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    imgs = [n.image for m in me.materials for n in m.node_tree.nodes if n.type == "TEX_IMAGE"]
    assert tris <= BUDGET, (name, tris)
    assert len(me.uv_layers) == 1 and len(me.color_attributes) == 0, name
    assert len(me.materials) <= 3 and len(imgs) == len(me.materials), (name, len(imgs))
    assert all(max(i.size) <= 2048 for i in imgs), name
    assert abs(lo.x + hi.x) < 0.05 and abs(lo.y + hi.y) < 0.05, (name, lo, hi)
    d = hi - lo
    print(f"SF {name}: {tris} tris, {len(me.materials)} mats, {d.x:.2f} x {d.z:.2f} x {d.y:.2f} m (w x h x d), "
          f"min height {lo.z:+.2f} m, {os.path.getsize(path) / 1e6:.2f} MB")
    if THUMBS:
        os.makedirs(THUMBS, exist_ok=True)
        sc = bpy.context.scene
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "STUDIO"
        sc.display.shading.color_type = "TEXTURE"
        sc.display.shading.show_backface_culling = True
        sc.render.resolution_x = sc.render.resolution_y = 512
        cam = bpy.data.objects.get("thumb_cam") or bpy.data.objects.new("thumb_cam", bpy.data.cameras.new("thumb_cam"))
        if cam.name not in sc.collection.objects:
            sc.collection.objects.link(cam)
        sc.camera = cam; cam.data.lens = 50; cam.data.clip_end = 10000
        ctr = (lo + hi) / 2; r = d.length
        for tag, dv in (("", Vector((1.0, -1.4, 0.55))), ("_back", Vector((-1.0, 1.4, 0.55)))):
            cam.location = ctr + dv.normalized() * r * 1.7
            cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(THUMBS, name + tag + ".png")
            bpy.ops.render.render(write_still=True)
    for x in new:
        bpy.data.objects.remove(x)


base = prepare_source()
built = []
for name, keep, drop, mode in OUTPUTS:
    built.append((build(base, name, keep, drop, mode), name))
for (path, tris), name in built:
    print(f"SF {name}: {tris} tris before budget")
    check_and_thumb(path, name)

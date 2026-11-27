# Extracts the ruin buildings from the "Desert ruins #MedievalRemixChallenge" Sketchfab diorama and exports them
# to assets/models/sf_dr_*.glb (re-runnable; the optional thumbnail dir renders a 512 px Workbench check per output):
#   blender --background --python blender/scripts/build_sf_dr_ruins.py [-- <thumbnail dir>]
# Same recipe as build_props.py: import, keep only the wanted nodes (by parent empty name), join, apply transforms,
# turn the door / passage to face +X, scale to metres (doorway ~2.5-3 m), origin bottom centre, export.
# The diorama is grey medieval stone; WARM tints it to sandstone so it sits in the sunset desert
# (texture pixels for the palette-atlas pieces, base colour factors for the flat-coloured shrine).
import bpy, os, sys, math, json, struct
import numpy as np
from mathutils import Vector, Matrix

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_desert_ruins.glb")
OUT = os.path.join(P, "assets", "models")
THUMBS = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv[:-1] else None
WARM = (1.25, 1.08, 0.82)          # grey stone -> sandstone multiplier
BUDGET = 40000

PIECES = [
    # output, parent empties to keep, yaw (deg) that turns the door/passage to +X, metres per source unit
    ("sf_dr_tower", ["mff_tower_base", "mff_tower_middle", "mff_tower_top",
                     "mff_tower_floor_half_mff_tower_half_floor", "mff_tower_floor_half_mff_tower_half_floor.001"], -100, 1.15),
    ("sf_dr_tower_stump", ["mff_tower_base.001", "mff_tower_top.002"], 50, 1.15),
    ("sf_dr_wall", ["mff_ruins_wall_0_Cube"], 50, 1.15),
    ("sf_dr_shrine", ["Grobowiec"], 50, 0.82),          # walk-through pavilion with a sarcophagus (Polish: grobowiec = tomb)
]


def tris(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def warm_atlas(obj, name):
    # palette-atlas pieces: drop the moss bushes (green strips, u > 0.25), then one material with a warm-tinted copy
    import bmesh
    bm = bmesh.new(); bm.from_mesh(obj.data)
    lay = bm.loops.layers.uv.active
    moss = [f for f in bm.faces if sum(l[lay].uv.x for l in f.loops) / len(f.loops) > 0.25]
    bmesh.ops.delete(bm, geom=moss, context="FACES")
    bm.to_mesh(obj.data); bm.free()
    src = next(n.image for m in obj.data.materials for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image)
    w, h = src.size
    px = np.empty(w * h * 4, np.float32); src.pixels.foreach_get(px); px = px.reshape(-1, 4)
    px[:, :3] = np.clip(px[:, :3] * WARM, 0, 1)
    img = bpy.data.images.new(name, w, h)          # new image so the exporter encodes the tinted pixels, not the packed original
    img.pixels.foreach_set(px.ravel()); img.file_format = "JPEG"
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    nt = mat.node_tree; bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.95
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    tex.interpolation = "Closest"                   # palette strips: no blending across strip borders
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.clear(); obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.material_index = 0
    return len(moss)


def warm_flat(obj):
    # flat-coloured pieces: keep their (<= 3) materials, tint the base colour factor
    for m in obj.data.materials:
        bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        c = bsdf.inputs["Base Color"].default_value
        bsdf.inputs["Base Color"].default_value = (*[min(1.0, c[k] * WARM[k]) for k in range(3)], 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95


def glb_info(path):
    with open(path, "rb") as f:
        f.read(12); n, _ = struct.unpack("<II", f.read(8)); j = json.loads(f.read(n))
    return len(j.get("meshes", [])), len(j.get("materials", [])), [i.get("mimeType") for i in j.get("images", [])]


def thumbnail(path, png):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.color_type = "TEXTURE"; sc.display.shading.show_backface_culling = True
    sc.render.resolution_x = sc.render.resolution_y = 512
    pts = [o.matrix_world @ Vector(c) for o in bpy.data.objects if o.type == "MESH" for c in o.bound_box]
    lo = Vector([min(p[k] for p in pts) for k in range(3)]); hi = Vector([max(p[k] for p in pts) for k in range(3)])
    # 1.8 m person-sized post at +X/-Y corner for scale
    bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=1.8, location=(hi.x + 1.0, lo.y - 1.0, 0.9))
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    c = (lo + hi) / 2; d = Vector((1, -1.1, 0.6)).normalized()
    cam.location = c + d * (hi - lo).length * 1.6
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler(); cam.data.clip_end = 1000
    sc.render.filepath = png
    bpy.ops.render.render(write_still=True)


for name, keep, yaw, mpu in PIECES:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.parent and o.parent.name in keep]
    assert meshes, name
    for o in meshes:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
    for o in list(bpy.data.objects):
        if o not in meshes:
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = obj.data.name = name

    has_tex = any(n.type == "TEX_IMAGE" for m in obj.data.materials for n in m.node_tree.nodes)
    removed = warm_atlas(obj, name) if has_tex else (warm_flat(obj) or 0)
    for a in list(obj.data.color_attributes) if has_tex else []:   # vertex colours only when there is no texture
        obj.data.color_attributes.remove(a)

    n = tris(obj)
    if n > BUDGET:   # not hit by these low-poly pieces; kept so a heavier selection stays in budget
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=1e-4); bpy.ops.object.mode_set(mode="OBJECT")
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = BUDGET / tris(obj)
        bpy.ops.object.modifier_apply(modifier="Decimate")

    obj.data.transform(Matrix.Rotation(math.radians(yaw), 4, "Z"))
    vs = [v.co for v in obj.data.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in obj.data.vertices:
        v.co = (v.co - pivot) * mpu
    obj.location = (0, 0, 0)
    obj.data.update()

    path = os.path.join(OUT, name + ".glb")
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, use_selection=True,
                              export_image_format="JPEG", export_normals=True)
    d = (hi - lo) * mpu
    out = tris(obj)
    nmesh, nmat, mimes = glb_info(path)
    assert out <= BUDGET and nmat <= 3 and nmesh == 1 and all(m == "image/jpeg" for m in mimes), (name, out, nmat, mimes)
    print(f"SFDR {name}: {n} -> {out} tris (moss faces removed {removed}), {d.x:.2f} x {d.z:.2f} x {d.y:.2f} m "
          f"(w x h x d), {nmat} materials, images {mimes}, {os.path.getsize(path) // 1024} KB")
    if THUMBS:
        os.makedirs(THUMBS, exist_ok=True)
        thumbnail(path, os.path.join(THUMBS, name + ".png"))

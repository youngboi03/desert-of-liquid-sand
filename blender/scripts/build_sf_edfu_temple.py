# Builds the Edfu temple landmark from the Sketchfab download and exports (re-runnable):
#   assets/models/sf_edfu_temple.glb  - pylon gateway + colonnaded forecourt (big landmark, 60-150 m out)
#   assets/models/sf_edfu_pylon.glb   - the pylon gateway alone
#   blender --background --python blender/scripts/build_sf_edfu_temple.py
# Source: "Tempel von Edfu" by TRYFIELD, CC-BY (assets/source/sketchfab_dl/license.txt).
# The source stores its greyscale photo textures in the metal/roughness slot (R = photo), so the base
# colour is rebuilt as R * sandstone tint. Untextured faces (pylon sides/tops, roofs) get a flat
# sandstone band added on top of the column texture, which keeps the output at 3 materials.
import bpy, os, numpy as np
from mathutils import Vector, Matrix

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_edfu_temple.glb")
OUT = os.path.join(P, "assets", "models")

PYLON_H = 30.0                        # real Edfu pylon is ~36 m; the whole source is pylon-height tall
TINT = np.array([0.93, 0.76, 0.54])   # sandstone (sRGB), multiplied with the greyscale photo
FLAT = TINT * 0.78                    # untextured faces
DROP = ("Plane004", "Object006")      # sand dune ground, little human figure
PYLON_MIN_Y = -100.0                  # source units: everything behind this belongs to the forecourt
BUDGET = 40000


def tinted(src_img, name, flat_band=False):
    w, h = src_img.size
    a = np.array(src_img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    rgb = a[:, :, :1] * TINT                             # R channel = greyscale photo
    if flat_band:                                        # extra top half: flat sandstone
        rgb = np.concatenate([rgb, np.broadcast_to(FLAT, (h, w, 3))], axis=0); h *= 2
    img = bpy.data.images.new(name, w, h)
    img.pixels[:] = np.concatenate([rgb, np.ones((h, w, 1))], axis=2).astype(np.float32).ravel()
    img.pack()
    return img


def material(name, img):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.95
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def build(name, pylon_only):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith(DROP)]
    if pylon_only:
        meshes = [o for o in meshes if o.name.startswith(("Object004", "Object005"))]
    for o in meshes:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
    for o in list(bpy.data.objects):
        if o not in meshes:
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = obj.data.name = name
    me = obj.data

    # drop the courtyard floor slab (huge horizontal faces at the base) and, for the pylon, the forecourt
    zmin = min(v.co.z for v in me.vertices)
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    kill = [f for f in bm.faces
            if (abs(f.normal.z) > 0.9 and f.calc_center_median().z < zmin + 1 and f.calc_area() > 1e5)
            or (pylon_only and f.calc_center_median().y < PYLON_MIN_Y)]
    print(f"{name}: removing {len(kill)} faces")
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me); bm.free()

    # 3 materials: relief photo (pylon front), engraving (pylon back), columns + flat band
    old = bpy.data.materials
    img_of = lambda m: next(n.image for n in m.node_tree.nodes if n.type == "TEX_IMAGE")
    srcs = [("edfu_relief", img_of(old["sand2_0"]), False),
            ("edfu_engraving", img_of(old["sand"]), False),
            ("edfu_stone", img_of(old["sand2_1"]), True)]
    remap = {"sand2_0": 0, "sand": 1, "sand2_1": 2, "sand2": 2}
    uv = me.uv_layers.active.data
    slot = [remap[m.name] for m in me.materials]
    for p in me.polygons:
        old_name = me.materials[p.material_index].name
        for li in p.loop_indices:
            if old_name == "sand2_1":
                u, v = uv[li].uv
                assert -0.01 <= v <= 1.01, ("column UV outside 0..1", v)
                uv[li].uv = (u, v * 0.5)                     # photo now fills the bottom half
            elif old_name == "sand2":
                uv[li].uv = (0.5, 0.75)                      # middle of the flat band
    idx = [slot[p.material_index] for p in me.polygons]
    me.materials.clear()                                 # this resets material_index, so restore it after
    for mname, img, band in srcs:
        me.materials.append(material(mname, tinted(img, mname, band)))
    me.polygons.foreach_set("material_index", idx)

    # face the gateway down +X (source front is +Y), scale to pylon height, origin bottom centre
    vs = [v.co for v in me.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    s = PYLON_H / (hi.z - lo.z)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    me.transform(Matrix.Rotation(-np.pi / 2, 4, "Z") @ Matrix.Scale(s, 4) @ Matrix.Translation(-pivot))
    me.update()

    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    assert tris <= BUDGET, (name, tris)
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True, export_image_format="JPEG")
    vs = [v.co for v in me.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    d = hi - lo
    print(f"EDFU {name}: {tris} tris, {d.x:.1f} x {d.z:.1f} x {d.y:.1f} m (w(x) x h x d), "
          f"x {lo.x:.1f}..{hi.x:.1f} y {lo.y:.1f}..{hi.y:.1f} z {lo.z:.2f}..{hi.z:.1f}")


build("sf_edfu_temple", pylon_only=False)
build("sf_edfu_pylon", pylon_only=True)

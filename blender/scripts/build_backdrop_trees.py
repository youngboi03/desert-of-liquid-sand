# Builds the dead-vegetation backdrop landmarks and exports them to assets/models/bg_*.glb
# (re-runnable, run in the background):
#   blender --background --python blender/scripts/build_backdrop_trees.py
# For each asset: import the Poly Haven glTF (vertices merged so decimation does not tear UV seams),
# join, decimate to the triangle budget, scale to the target size, origin bottom centre, apply
# transforms, give it ONE material with only its base-colour texture and export a Y-up .glb.
# The quiver tree has a trunk and a leaf material: both diffuse maps are packed side by side into
# one 1024 px atlas and the UVs are remapped, so it also ends up with a single material and image.
import bpy, os, tempfile
import numpy as np
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source")
OUT = os.path.join(P, "assets", "models")

ASSETS = [
    # name, source id, max triangles, size (axis "height" = z, "length" = longest axis, metres)
    ("bg_dead_tree_trunk_02", "dead_tree_trunk_02", 12000, ("length", 5.0)),  # fallen log
    ("bg_dead_quiver_trunk",  "dead_quiver_trunk",  12000, ("height", 4.0)),  # standing dead trunk
    ("bg_quiver_tree_01",     "quiver_tree_01",     12000, ("height", 6.0)),  # living quiver tree
    ("bg_dead_tree_trunk",    "dead_tree_trunk",    12000, ("length", 4.0)),  # fallen log
]


def diffuse_image(mat):
    """The image plugged (directly or through nodes) into the Base Color of an imported material."""
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and "diff" in n.image.name:
            return n.image
    raise RuntimeError(f"no diffuse texture in {mat.name}")


def atlas(images, name):
    """Packs the images side by side (each squeezed to 1024/len x 1024) into one 1024 px JPEG."""
    w = 1024 // len(images)
    out = np.zeros((1024, 1024, 4), np.float32)
    for i, img in enumerate(images):
        img = img.copy(); img.scale(w, 1024)
        px = np.empty(w * 1024 * 4, np.float32); img.pixels.foreach_get(px)
        out[:, i * w:(i + 1) * w] = px.reshape(1024, w, 4)
        bpy.data.images.remove(img)
    res = bpy.data.images.new(name, 1024, 1024)
    res.pixels.foreach_set(out.ravel())
    res.filepath_raw = os.path.join(tempfile.gettempdir(), name + ".jpg"); res.file_format = "JPEG"
    res.save(); res.pack()       # packed, so the exporter embeds it regardless of the temp file
    return res


bpy.ops.wm.read_factory_settings(use_empty=True)
for name, sid, budget, (axis, size) in ASSETS:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, "bg_" + sid, sid + "_1k.gltf"), merge_vertices=True)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
    for o in new:
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
    me = obj.data

    # One material: a single diffuse map, or an atlas of several (UV u squeezed into its slot).
    mats = [m for m in me.materials]
    imgs = [diffuse_image(m) for m in mats]
    uv = me.uv_layers.active.data
    co = np.empty(len(uv) * 2, np.float32); uv.foreach_get("uv", co)
    assert co.min() >= -0.001 and co.max() <= 1.001, f"{name}: UVs outside [0,1], atlas would break"
    if len(imgs) > 1:
        img = atlas(imgs, name + "_diff")
        for p in me.polygons:
            for li in p.loop_indices:
                u = uv[li].uv
                uv[li].uv = ((p.material_index + u.x) / len(imgs), u.y)
    else:
        img = imgs[0]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.9
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.clear(); me.materials.append(mat)
    for p in me.polygons:
        p.material_index = 0

    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    if tris > budget:
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = budget / tris * 0.98
        bpy.ops.object.modifier_apply(modifier="Decimate")

    vs = [v.co for v in me.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    s = size / ((hi.z - lo.z) if axis == "height" else max(hi - lo))
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in me.vertices:
        v.co = (v.co - pivot) * s
    obj.location = (0, 0, 0)

    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True, export_image_format="JPEG")
    dims = (hi - lo) * s
    print(f"BACKDROP {name}: {tris} -> {sum(len(p.vertices) - 2 for p in me.polygons)} tris, "
          f"{len(me.vertices)} verts, {dims.x:.2f} x {dims.z:.2f} x {dims.y:.2f} m (w x h x d)")
    obj.hide_set(True)    # keep it out of the next asset's selection

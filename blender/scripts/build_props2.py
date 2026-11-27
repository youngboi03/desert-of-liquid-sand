# Builds the Poly Haven statue / vessel props and exports them to assets/models/<name>.glb (re-runnable):
#   blender --background --python blender/scripts/build_props2.py
# Same recipe as build_props.py / build_backdrop_rocks.py: import the Poly Haven glTF
# (assets/source/<id>/<id>_1k.gltf), join, turn it so the face looks along glTF +Z (Blender -Y),
# decimate to the triangle budget, scale to the target height, origin bottom centre, then give it ONE
# material that only carries the base-colour texture (embedded in the GLB). The authored UVs are kept.
import bpy, os, math
from mathutils import Vector, Matrix

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source")
OUT = os.path.join(P, "assets", "models")

PROPS = [
    # name = Poly Haven id, max triangles, height (m), yaw about up (deg) so the face points at Blender -Y
    ("lion_head",               12000, 4.0, 0),
    ("bull_head",               12000, 3.5, 0),
    ("marble_bust_01",          12000, 5.0, 0),
    ("concrete_cat_statue",     10000, 2.8, 0),
    ("antique_ceramic_vase_01",  5000, 1.6, 0),
]


def base_color_image(mats):
    for m in mats:
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and "diff" in n.image.name.lower():
                    return n.image
    raise RuntimeError("no base colour texture found")


def single_material(obj, name):
    img = base_color_image(obj.data.materials)
    if max(img.size) > 1024:
        img.scale(1024, 1024)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.9
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.material_index = 0
    return img


bpy.ops.wm.read_factory_settings(use_empty=True)
for name, budget, height, yaw in PROPS:
    for o in list(bpy.data.objects):                    # one prop at a time in an empty scene
        bpy.data.objects.remove(o)
    # merge_vertices: glTF splits vertices on UV seams; without welding, decimate tears cracks along them
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, name, name + "_1k.gltf"), merge_vertices=True)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
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
    obj.matrix_world = Matrix.Rotation(math.radians(yaw), 4, "Z") @ obj.matrix_world
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = obj.data.name = name

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > budget:
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = budget / tris * 0.98
        bpy.ops.object.modifier_apply(modifier="Decimate")

    vs = [v.co for v in obj.data.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    s = height / (hi.z - lo.z)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in obj.data.vertices:
        v.co = (v.co - pivot) * s
    obj.location = (0, 0, 0)
    obj.data.update()

    img = single_material(obj, name)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True)
    d = (hi - lo) * s
    out_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    assert out_tris <= budget, (name, out_tris)
    print(f"PROP {name}: {tris} -> {out_tris} tris, {d.x:.2f} x {d.z:.2f} x {d.y:.2f} m (w x h x d), "
          f"texture {img.name} {tuple(img.size)}")

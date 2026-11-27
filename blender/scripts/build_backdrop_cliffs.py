# Builds the horizon cliff backdrops and exports them to assets/models/bg_*.glb (run in the background):
#   blender --background --python blender/scripts/build_backdrop_cliffs.py
# Same steps as build_props.py: import the Poly Haven glTF, keep the meshes, join, decimate to the budget,
# scale to the target height, origin bottom centre, then give it ONE material with only the base-colour
# texture (normal/ARM maps are dropped: at 40-200 m in fog they are invisible and cost extra images).
# Re-runnable: it starts from factory settings and overwrites the .glb files.
import bpy, os
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source")
OUT = os.path.join(P, "assets", "models")

CLIFFS = [
    # name, source glTF, max triangles, target height (m)
    ("bg_cliff_01", "bg_namaqualand_cliff_01/namaqualand_cliff_01_1k.gltf", 30000, 25.0),
    ("bg_cliff_02", "bg_namaqualand_cliff_02/namaqualand_cliff_02_1k.gltf", 30000, 30.0),
]

def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)

def base_colour_material(name, image):
    # Image Texture -> Principled Base Color, matte rock: the only image the exporter will embed.
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = image
    bsdf.inputs["Roughness"].default_value = 0.95
    bsdf.inputs["Metallic"].default_value = 0.0
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, src, budget, height in CLIFFS:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, src))
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

    tris = tri_count(obj)
    if tris > budget:
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = budget / tris
        bpy.ops.object.modifier_apply(modifier="Decimate")

    vs = [v.co for v in obj.data.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    s = height / (hi.z - lo.z)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in obj.data.vertices:
        v.co = (v.co - pivot) * s
    obj.location = (0, 0, 0)

    # Swap the imported PBR material for a single base-colour-only one.
    folder = src.split("/")[0]  # bg_<id>
    diff = bpy.data.images.load(os.path.join(SRC, folder, "textures", folder[3:] + "_diff_1k.jpg"), check_existing=True)
    assert max(diff.size) <= 1024, diff.size
    obj.data.materials.clear()
    obj.data.materials.append(base_colour_material(name, diff))

    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True)
    d = obj.dimensions
    print(f"BACKDROP {name}: {tris} -> {tri_count(obj)} tris, {d.x:.1f} x {d.z:.1f} x {d.y:.1f} m (w x h x d)")
    obj.hide_set(True)  # keep the next cliff's selection clean

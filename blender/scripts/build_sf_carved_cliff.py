# Builds assets/models/sf_carved_cliff.glb from the Sketchfab scan "Ancient Carved Stone Cliff 4" (re-runnable):
#   blender --background --python blender/scripts/build_sf_carved_cliff.py
# Same recipe as build_backdrop_rocks.py: import, join, apply transforms, scale to WIDTH metres along X,
# origin bottom centre, one material carrying only the base-colour texture (embedded as JPEG).
# The scan is a closed rock arch; its Sketchfab front (Blender -Y) already exports as glTF +Z, so no rotation.
import bpy, os
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_carved_cliff.glb")
OUT = os.path.join(P, "assets", "models", "sf_carved_cliff.glb")
NAME, WIDTH, BUDGET = "sf_carved_cliff", 35.0, 40000
assert os.path.normcase(SRC) != os.path.normcase(OUT)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC, merge_vertices=True)
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
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
obj.name = obj.data.name = NAME

tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
if tris > BUDGET:
    mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = BUDGET / tris
    bpy.ops.object.modifier_apply(modifier="Decimate")

vs = [v.co for v in obj.data.vertices]
lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
s = WIDTH / (hi.x - lo.x)
pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
for v in obj.data.vertices:
    v.co = (v.co - pivot) * s
obj.data.update()

# the source material also feeds a normal and a roughness map: keep only the image wired to Base Color
src_bsdf = next(n for m in obj.data.materials for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
img = src_bsdf.inputs["Base Color"].links[0].from_node.image
if max(img.size) > 2048:
    img.scale(2048, 2048)
mat = bpy.data.materials.new(NAME)
mat.use_nodes = True
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Roughness"].default_value = 0.95
tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
obj.data.materials.clear()
obj.data.materials.append(mat)
for p in obj.data.polygons:
    p.material_index = 0
for a in list(obj.data.color_attributes):
    obj.data.color_attributes.remove(a)
for uv in [u for u in obj.data.uv_layers if not u.active_render]:   # the scan carries 2 unused extra UV sets
    obj.data.uv_layers.remove(uv)

bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, use_selection=True,
                          export_image_format="JPEG")
out_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
d = (hi - lo) * s
assert out_tris <= BUDGET, out_tris
assert abs(d.x - WIDTH) < 0.01
print(f"CLIFF {NAME}: {tris} -> {out_tris} tris, {d.x:.2f} x {d.z:.2f} x {d.y:.2f} m (w x h x d), tex {tuple(img.size)}")

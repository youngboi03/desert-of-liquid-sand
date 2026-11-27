# Builds assets/models/sf_egyptian_ruins.glb from the Sketchfab "Egyptian Ruins" download (re-runnable):
#   blender --background --python blender/scripts/build_sf_egyptian_ruins.py
# Same recipe as build_backdrop_rocks.py: import (welding UV-seam vertices), keep the three sandstone meshes
# (drop the stray 2 m "Icosphere", the armature and the empties), join, decimate to the triangle budget,
# origin bottom centre, export with the base-colour textures embedded as JPEG. The source is already in metres.
import bpy, os, math
from mathutils import Matrix, Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_egyptian_ruins.glb")
OUT = os.path.join(P, "assets", "models", "sf_egyptian_ruins.glb")
NAME, BUDGET = "sf_egyptian_ruins", 38000

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC, merge_vertices=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name != "Icosphere" and o.data.materials]
assert len(meshes) == 3, [o.name for o in meshes]
for o in meshes:
    for m in list(o.modifiers):                         # skinned to a static armature: rest pose is the shape
        o.modifiers.remove(m)
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
# passage (entrance steps -> open back) ran along Blender -Y -> +Y; turn it to the house walk-through axis X,
# steps facing -X so the camel (travelling +X) climbs them on the way in
obj.matrix_world = Matrix.Rotation(-math.pi / 2, 4, "Z") @ obj.matrix_world   # glTF import uses quaternion mode
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
obj.name = obj.data.name = NAME
for vg in list(obj.vertex_groups):
    obj.vertex_groups.remove(vg)

tri_count = lambda: sum(len(p.vertices) - 2 for p in obj.data.polygons)
tris = tri_count()
if tris > BUDGET:
    mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = BUDGET / tris; mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="Decimate")

vs = [v.co for v in obj.data.vertices]
lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
for v in obj.data.vertices:
    v.co -= pivot
obj.location = (0, 0, 0)
obj.data.update()

for m in obj.data.materials:                            # dry sandstone, base colour texture only
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.95
    bsdf.inputs["Metallic"].default_value = 0.0
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and max(n.image.size) > 2048:
            n.image.scale(2048, 2048)

out_tris = tri_count()
assert out_tris <= 40000 and len(obj.data.materials) <= 3, (out_tris, len(obj.data.materials))
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, use_selection=False,
                          export_image_format="JPEG", export_materials="EXPORT", export_skins=False,
                          export_animations=False, export_cameras=False, export_lights=False)
d = hi - lo
print(f"SF {NAME}: {tris} -> {out_tris} tris, {d.x:.2f} x {d.z:.2f} x {d.y:.2f} m (w x h x d)")

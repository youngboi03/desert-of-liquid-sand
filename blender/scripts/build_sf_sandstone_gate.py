# Builds assets/models/sf_sandstone_gate.glb from the Sketchfab download (re-runnable):
#   blender --background --python blender/scripts/build_sf_sandstone_gate.py [-- <thumbnail.png>]
# Same recipe as build_backdrop_rocks.py: import, keep the one mesh, apply transforms, scale so the
# arch opening is 4.5 m tall (gate ~6 m), origin bottom centre, ONE material carrying only the base-colour texture
# (embedded JPEG). The source already has its passage along X (thin side), so no rotation is needed:
# a camel walking along +X goes through the opening.
import bpy, os, sys
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_sandstone_gate.glb")
OUT = os.path.join(P, "assets", "models", "sf_sandstone_gate.glb")
NAME = "sf_sandstone_gate"
OPENING = 4.5          # target clear height of the arch opening (m); the opening is ~75 % of the height -> gate ~6 m
BUDGET = 40000
THUMB = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None

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
# the opening reaches the ground, so its height = lowest vertex in a thin slice through the gate's centre (y ~ 0)
cy = (lo.y + hi.y) / 2
gap = min(v.z for v in vs if abs(v.y - cy) < 0.02 * (hi.y - lo.y)) - lo.z
# clear width: largest horizontal gap between vertices in the bottom 30 %
ys = sorted(v.y for v in vs if v.z < lo.z + 0.3 * (hi.z - lo.z))
width = max(b - a for a, b in zip(ys, ys[1:]))
s = OPENING / gap
pivot = Vector(((lo.x + hi.x) / 2, cy, lo.z))
for v in obj.data.vertices:
    v.co = (v.co - pivot) * s
obj.location = (0, 0, 0)
obj.data.update()

# one material: base colour texture only (the source also has a normal map and ORM texture)
src_mat = obj.data.materials[0]
bsdf_src = next(n for n in src_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
img = bsdf_src.inputs["Base Color"].links[0].from_node.image
if max(img.size) > 2048:
    img.scale(2048, 2048)
mat = bpy.data.materials.new(NAME)
mat.use_nodes = True
nt = mat.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Roughness"].default_value = 0.95
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; nt.nodes.active = tex
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
obj.data.materials.clear()
obj.data.materials.append(mat)
for p in obj.data.polygons:
    p.material_index = 0
uv_used = obj.data.uv_layers.active.name
for uv in [u for u in obj.data.uv_layers if u.name != uv_used]:   # source carries 4 UV sets; only the first is used
    obj.data.uv_layers.remove(uv)

d = (hi - lo) * s
out_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
assert out_tris <= BUDGET, out_tris
assert 5.5 < d.z < 8.0, d.z              # gate should end up ~6-7 m tall
assert 1.5 < width * s < d.y * 0.8, width * s   # a real walk-through gap, not a masonry crack
print(f"GATE {NAME}: {tris} -> {out_tris} tris, glTF X (passage/thickness) {d.x:.2f} m, Y (height) {d.z:.2f} m, "
      f"Z (span) {d.y:.2f} m; opening {gap * s:.2f} m high x {width * s:.2f} m clear width; scale {s:.3f}")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, use_selection=True,
                          export_image_format="JPEG", export_materials="EXPORT")

if THUMB:
    # Workbench thumbnail, textured, backface culling on, with a 1.8 m reference post
    scene = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, d.y * 0.5 + 1.0, 0.9)); bpy.context.object.scale = (0.3, 0.3, 1.8)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_backface_culling = True
    scene.render.resolution_x = scene.render.resolution_y = 512
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam)
    scene.camera = cam
    target = Vector((0, 0, d.z * 0.45))
    for suffix, view in (("", (1.0, -0.75, 0.25)), ("_back", (-1.0, 0.75, 0.25))):
        cam.location = target + Vector(view).normalized() * d.z * 2.2
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = THUMB.replace(".png", suffix + ".png")
        bpy.ops.render.render(write_still=True)

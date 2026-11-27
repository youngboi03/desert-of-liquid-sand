# Import step for explorer.blend (run once, in the background):
#   blender --background --python blender/scripts/import_explorer.py
# (an output path after -- writes a fresh copy elsewhere, e.g. to re-import one part)
# Joins the Sketchfab "Fremen of Dune" parts into two meshes (Body, Cloak), scales the figure to
# 1.8 m with the feet at the origin, and saves blender/explorer.blend. Rigging is done in that file.
import bpy, os, sys
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(P, "assets", "source", "explorer", "fremen_of_dune.glb"))
scene = bpy.context.scene
meshes = [o for o in scene.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
for o in list(scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)

def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    o = bpy.context.view_layer.objects.active
    o.name = o.data.name = name
    return o

cloak_parts = [o for o in meshes if "cloak" in o.name]
body_parts = [o for o in meshes if "cloak" not in o.name]
cloak = join(cloak_parts, "Cloak")
body = join(body_parts, "Body")

vs = [v.co for o in (body, cloak) for v in o.data.vertices]
lo = Vector([min(v[i] for v in vs) for i in range(3)])
hi = Vector([max(v[i] for v in vs) for i in range(3)])
s = 1.8 / (hi.z - lo.z)
c = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
col = bpy.data.collections.new("Explorer")
scene.collection.children.link(col)
for o in (body, cloak):
    for v in o.data.vertices:
        v.co = (v.co - c) * s
    for cc in list(o.users_collection):
        cc.objects.unlink(o)
    col.objects.link(o)
bpy.ops.file.pack_all()
# optional: blender --background --python import_explorer.py -- <output.blend>
out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(P, "blender", "explorer.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print("saved explorer.blend")

# Builds blender/props.blend and exports the static props to assets/models/ (run in the background):
#   blender --background --python blender/scripts/build_props.py
# For each prop: import the downloaded file, keep only the useful meshes, decimate to a real-time
# budget, scale it, move the origin (bottom centre, or top ring for the lantern) and export a .glb.
import bpy, os
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source")
OUT = os.path.join(P, "assets", "models")

PROPS = [
    # name, source file, keep meshes whose name contains, max triangles, size, origin
    ("Arch",    "arch/palmyra_arch.glb",             ["Object_3"],         15000, ("height", 7.0), "bottom"),
    ("Ruins",   "ruins/ancient_ruins.glb",           ["Stone"],             6000, ("height", 5.0), "bottom"),
    ("Pillar",  "pillar/sandstone_pillar.glb",       [""],                  2000, ("height", 4.0), "bottom"),
    ("Boulder", "boulder/namaqualand_boulder_04.gltf", [""],                6000, ("height", 1.9), "center"),
    ("Lantern", "lantern/Lantern_01.gltf",           [""],                  6000, ("height", 0.29), "top"),
]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
for i, (name, src, keep, budget, (_, size), origin) in enumerate(PROPS):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, src))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and any(k in o.name for k in keep)]
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

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > budget:
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = budget / tris
        bpy.ops.object.modifier_apply(modifier="Decimate")

    vs = [v.co for v in obj.data.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    s = size / (hi.z - lo.z)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, {"bottom": lo.z, "top": hi.z, "center": (lo.z + hi.z) / 2}[origin]))
    for v in obj.data.vertices:
        v.co = (v.co - pivot) * s
    obj.location = (0, 0, 0)

    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name.lower() + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True)
    col = bpy.data.collections.new(name); scene.collection.children.link(col)
    for c in list(obj.users_collection): c.objects.unlink(obj)
    col.objects.link(obj)
    obj.location = (i * 9.0, 0, 0)          # lay the props out side by side in props.blend
    print(f"PROP {name}: {tris} -> {sum(len(p.vertices) - 2 for p in obj.data.polygons)} tris")

bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(P, "blender", "props.blend"))
print("saved props.blend")

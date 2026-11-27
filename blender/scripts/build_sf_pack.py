# Builds four ruin pieces out of the Sketchfab "Ancient Ruins Pack" and exports them to
# assets/models/sf_pack_<name>.glb (re-runnable):
#   blender --background --python blender/scripts/build_sf_pack.py [-- <thumbnail dir>]
# The pack is laid out flat as 12 numbered little scenes (Bricks<N> + Pillar<N> + Wall(s)<N>). Each output
# is one numbered scene: import, keep its meshes, join, apply transforms, scale x2 (walls 4 m, pillars
# 6 m), origin bottom centre (source ground z=0 -> y=0; loose bricks sink 0.16 m), base-colour-only
# materials with the slate-blue bricks recoloured to warm sandstone, embedded JPEG.
import bpy, os, re, sys, math
import numpy as np
from mathutils import Vector

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_ancient_ruins_pack.glb")
OUT = os.path.join(P, "assets", "models")
THUMBS = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None

SCALE = 2.0
BUDGET = 40000
SAND = np.array([0.80, 0.63, 0.45])      # sRGB target average for the recoloured texture

PIECES = [
    # output stem, numbered pack scenes to keep
    ("sf_pack_room",   {10}),   # corner of a room: two walls, three pillars, broken columns, rubble
    ("sf_pack_tower",  {7}),    # tall broken pillar with two crossing stepped walls
    ("sf_pack_wall",   {6}),    # stepped broken wall corner with a pillar
    ("sf_pack_rubble", {4}),    # fallen column drums and capitals
]


def sandstone(img):
    # luminance-preserving remap of the slate-blue/mossy texture onto sandstone (UV padding stays black)
    px = np.empty(len(img.pixels), dtype=np.float32); img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    lum = px[:, :3] @ np.array([0.299, 0.587, 0.114])
    mean = lum[lum > 0.02].mean()
    px[:, :3] = np.clip(lum[:, None] / mean * SAND, 0, 1)
    img.pixels.foreach_set(px.ravel()); img.update()


def base_only(mat):
    # new material carrying only the base-colour texture (drops the metal/roughness map)
    img = next(l.from_node.image for l in next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
               .inputs["Base Color"].links)
    if max(img.size) > 2048:
        img.scale(2048, 2048)
    sandstone(img)
    new = bpy.data.materials.new(mat.name + "_base")
    new.use_nodes = True
    nt = new.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.95
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return new


def thumbnail(obj, path):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.color_type = "TEXTURE"; sh.light = "STUDIO"; sh.show_backface_culling = True
    sc.render.resolution_x = sc.render.resolution_y = 512
    world = sc.world or bpy.data.worlds.new("w"); sc.world = world
    world.color = (0.45, 0.5, 0.55)
    cam = bpy.data.objects.new("thumb_cam", bpy.data.cameras.new("thumb_cam"))
    sc.collection.objects.link(cam); sc.camera = cam
    d = obj.dimensions
    c = Vector((0, 0, d.z / 2)); r = d.length / 2
    v = Vector((0.75, -1.0, 0.55)).normalized()
    cam.location = c + v * r * 2.4
    cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


for name, groups in PIECES:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # merge_vertices: glTF splits vertices on UV seams; weld so any decimation cannot tear cracks
    bpy.ops.import_scene.gltf(filepath=SRC, merge_vertices=True)
    meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and int(re.search(r"\d+", o.name).group()) in groups]
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

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > BUDGET:
        mod = obj.modifiers.new("Decimate", "DECIMATE"); mod.ratio = BUDGET / tris
        bpy.ops.object.modifier_apply(modifier="Decimate")

    vs = [v.co for v in obj.data.vertices]
    lo = Vector([min(v[k] for v in vs) for k in range(3)]); hi = Vector([max(v[k] for v in vs) for k in range(3)])
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0.0))   # authored ground plane is z=0
    for v in obj.data.vertices:
        v.co = (v.co - pivot) * SCALE
    obj.location = (0, 0, 0)
    obj.data.update()

    for i, m in enumerate(obj.data.materials):
        obj.data.materials[i] = base_only(m)
    while len(obj.data.uv_layers) > 1:          # engine only reads UV0; the pack carries an unused 2nd set
        obj.data.uv_layers.remove(obj.data.uv_layers[-1])
    while obj.data.color_attributes:
        obj.data.color_attributes.remove(obj.data.color_attributes[0])

    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True, export_image_format="JPEG")
    out_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    assert out_tris <= BUDGET * 1.02 and len(obj.data.materials) <= 3, (name, out_tris)
    d = obj.dimensions
    print(f"PIECE {name}: {tris} -> {out_tris} tris, {len(obj.data.materials)} mats, "
          f"{d.x:.2f} x {d.z:.2f} x {d.y:.2f} m (w x h x d), lowest y {(lo.z - pivot.z) * SCALE:.2f}")
    if THUMBS:   # render the exported file itself, so the thumbnail shows what the engine will load
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=os.path.join(OUT, name + ".glb"))
        thumbnail(next(o for o in bpy.data.objects if o.type == "MESH"), os.path.join(THUMBS, name + ".png"))

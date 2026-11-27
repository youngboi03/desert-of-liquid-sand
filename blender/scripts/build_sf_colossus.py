# Builds assets/models/sf_colossus.glb from the Sketchfab "Colossus" (CC-BY, see sketchfab_dl/license.txt):
#   blender --background --python blender/scripts/build_sf_colossus.py
# The source is a T-posed bronze colossus (no armature). A T-pose reads as a game character, so the arms
# are snapped off at the shoulders (broken ruin statue), the glow strip / arm wraps / eye bits are
# dropped (the thigh wrap is kept, recoloured bronze), the 8 per-part 256 px textures go into one 1024 atlas, and the figure stands on a sandstone
# plinth. Result: 3 materials (atlas, feet - their UVs tile so they keep their own texture, plinth colour).
import bpy, bmesh, os
import numpy as np
from mathutils import Vector, Matrix

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source", "sketchfab_dl", "sf_colossus.glb")
OUT = os.path.join(P, "assets", "models", "sf_colossus.glb")

FIGURE_H = 17.0                  # bronze figure height (m), plinth adds PLINTH_H
PLINTH = (5.6, 4.2)              # plinth width (x) x depth (m)
PLINTH_H, SKIRT = 1.6, 0.3       # plinth top above ground, part sunk below y=0
DROP = {"Object_3", "Object_8"}   # eye bits (untextured), blue glow strip
WRAP = "Object_7"                # alpha-cut wraps: arm part dropped, thigh part kept (leg mesh has a hole under it)
FEET = "Object_12"               # UVs span several tiles (repeat) -> own material
CUT_X = 30.0                     # shoulder break, source units (torso incl. sleeves is +-34, legs +-22)
BUDGET = 40000

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC, merge_vertices=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in DROP]
for o in meshes:
    mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
for o in list(bpy.data.objects):
    if o not in meshes:
        bpy.data.objects.remove(o)
wrap = bpy.data.objects[WRAP]
bm = bmesh.new(); bm.from_mesh(wrap.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if max((wrap.matrix_world @ v.co).z for v in f.verts) >= 120], context="FACES")
bm.to_mesh(wrap.data); bm.free()


def base_image(obj):
    m = obj.data.materials[0]
    link = next(l for l in m.node_tree.links if l.to_socket.name == "Base Color")
    return link.from_node.image


def flat_material(name, img=None, color=(0.8, 0.8, 0.8, 1)):
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.8
    bsdf.inputs["Base Color"].default_value = color
    if img:
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


# --- atlas: every part's UVs sit inside one integer tile, so shift to 0..1 and pack 4x4 tiles of 256 px
body = [o for o in meshes if o.name != FEET]
T, N = 256, 4
atlas_px = np.zeros((N * T, N * T, 4), np.float32); atlas_px[..., 3] = 1
pad = 1.5 / T                                     # keep samples off the tile edge (bilinear bleed)
for i, o in enumerate(body):
    img = base_image(o)
    if tuple(img.size) != (T, T):
        img.scale(T, T)
    px = np.empty(T * T * 4, np.float32); img.pixels.foreach_get(px)
    if o is wrap:                                 # no alpha in the engine: recolour the dark strap bronze
        px = px.reshape(-1, 4); lum = px[:, :3] @ np.array([0.3, 0.59, 0.11], np.float32)
        lum[px[:, 3] < 0.5] = 0.05
        px[:, :3] = np.outer(0.45 + 1.2 * lum, (0.55, 0.40, 0.16)); px[:, 3] = 1
    col, row = i % N, i // N
    atlas_px[row * T:(row + 1) * T, col * T:(col + 1) * T] = px.reshape(T, T, 4)
    uv = o.data.uv_layers.active.data
    uvs = np.empty(len(uv) * 2, np.float32); uv.foreach_get("uv", uvs); uvs = uvs.reshape(-1, 2)
    uvs -= np.floor(uvs.min(0) + 1e-3)            # into 0..1 of its own tile
    assert uvs.min() > -0.01 and uvs.max() < 1.01, (o.name, uvs.min(0), uvs.max(0))
    uvs = (np.array([col, row]) + pad + np.clip(uvs, 0, 1) * (1 - 2 * pad)) / N
    uv.foreach_set("uv", uvs.ravel())
atlas = bpy.data.images.new("sf_colossus_atlas", N * T, N * T)
atlas.pixels.foreach_set(atlas_px.ravel())
atlas.file_format = "JPEG"; atlas.pack()
m_body = flat_material("sf_colossus_bronze", atlas)
feet = next(o for o in meshes if o.name == FEET)
m_feet = flat_material("sf_colossus_feet", base_image(feet))
for o in meshes:
    o.data.materials.clear(); o.data.materials.append(m_feet if o is feet else m_body)

# --- join, break the arms off, scale, stand on a plinth
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
obj.name = obj.data.name = "sf_colossus"

bm = bmesh.new(); bm.from_mesh(obj.data)
for sx, n in ((1, Vector((1, 0.2, 0.12))), (-1, Vector((-1, -0.15, 0.1)))):   # slanted, uneven breaks
    n.normalize()
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(sx * CUT_X, 0, 170), plane_no=n, clear_outer=True)
    cut_edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    bmesh.ops.holes_fill(bm, edges=cut_edges, sides=0)    # cap the stumps (best effort, shells overlap)
bm.to_mesh(obj.data); bm.free()

vs = np.empty(len(obj.data.vertices) * 3, np.float32); obj.data.vertices.foreach_get("co", vs); vs = vs.reshape(-1, 3)
lo, hi = vs.min(0), vs.max(0)
s = FIGURE_H / (hi[2] - lo[2])
pivot = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
vs = (vs - pivot) * s
vs[:, :2] *= -1                                   # yaw 180: face looks Blender -Y = glTF +Z
vs[:, 2] += PLINTH_H
obj.data.vertices.foreach_set("co", vs.ravel()); obj.data.update()

bm = bmesh.new(); bm.from_mesh(obj.data)
box = bmesh.ops.create_cube(bm, size=1.0)["verts"]
bmesh.ops.transform(bm, verts=box, matrix=Matrix.Diagonal((PLINTH[0], PLINTH[1], PLINTH_H + SKIRT, 1)))
bmesh.ops.translate(bm, verts=box, vec=(0, 0, (PLINTH_H - SKIRT) / 2))
bm.to_mesh(obj.data); bm.free()
m_stone = flat_material("sf_colossus_plinth", color=(0.62, 0.48, 0.32, 1))
obj.data.materials.append(m_stone)
box_ids = set(range(len(obj.data.vertices) - 8, len(obj.data.vertices)))
for p in obj.data.polygons:
    if set(p.vertices) <= box_ids:
        p.material_index = 2
        p.use_smooth = False

tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
assert tris <= BUDGET, tris
assert len(obj.data.materials) == 3
bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, use_selection=True,
                          export_image_format="JPEG")
d = vs.max(0) - vs.min(0)
print(f"COLOSSUS: {tris} tris, figure {d[0]:.2f} x {d[2]:.2f} x {d[1]:.2f} m, plinth {PLINTH} total h {FIGURE_H + PLINTH_H:.1f} m")

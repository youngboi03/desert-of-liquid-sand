# Improves the explorer's rig in blender/explorer.blend and re-exports assets/models/explorer.glb.
# Run it in the background (it can be re-run: the weights are recomputed from scratch each time, so a
# second run only changes them by float rounding, < 0.001; Blender also keeps the previous file as .blend1):
#   blender --background --python blender/scripts/rig_explorer.py
#
# What it does:
#   1. Adds three cloak bones (Cloak.Back, Cloak.L, Cloak.R, all children of Chest) so the lower cape
#      can swing on its own. The 19 old bones keep their names, parents and rest pose (the seated pose).
#   2. Body: re-splits each vertex's torso weight (Hips + Spine + Chest + Neck + Head) by height, so the
#      back bends smoothly: pelvis -> Hips, belly -> Spine, chest -> Chest, neck -> Neck, head -> Head,
#      with soft blends across every joint. Arm and leg weights are left as they were.
#      The head pieces (mask, eyes) stay 100 % Head so the face never bends.
#   3. Cloak: the upper cloak copies the weights of the body underneath it (so it moves with the body
#      and does not cut into it); further down the cape fades into the cloak bones.
#   4. Keeps at most 4 bones per vertex (the game shader's limit), saves the .blend and exports the .glb
#      with the same settings as before (GLB, Y up, only the explorer objects).
#
# Rig frame (as in the game): the explorer faces Blender -Y, his left is +X, up is +Z.
import bpy, os
import numpy as np
from mathutils import Vector, kdtree

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLEND = os.path.join(P, "blender", "explorer.blend")
GLB = os.path.join(P, "assets", "models", "explorer.glb")

OLD_BONES = ["Hips", "Spine", "Chest", "Neck", "Head", "Shoulder.L", "UpperArm.L", "Forearm.L", "Hand.L",
             "Shoulder.R", "UpperArm.R", "Forearm.R", "Hand.R", "Thigh.L", "Shin.L", "Foot.L",
             "Thigh.R", "Shin.R", "Foot.R"]
TORSO = ["Hips", "Spine", "Chest", "Neck", "Head"]

# New bones: name -> (parent, head, tail) in Blender coordinates (metres).
# All three hang from Chest: the cape is one sheet hanging from the shoulders. (The game rocks the Hips
# +-0.16 rad every stride while the chest stays upright, so hip-parented side panels would tear the cape.)
# Each head sits at the top of the cape's weight ramp (z = 1.30), so the cape bends there, not lower.
CLOAK_BONES = {
    "Cloak.Back": ("Chest", (0.00, 0.17, 1.32), (0.00, 0.17, 0.30)),    # middle of the cape, down the back
    "Cloak.L":    ("Chest", (0.20, 0.12, 1.32), (0.42, 0.12, 0.25)),    # left half of the cape (+X)
    "Cloak.R":    ("Chest", (-0.20, 0.12, 1.32), (-0.42, 0.12, 0.25)),  # right half of the cape
}


def smoothstep(e0, e1, x):
    """0 at e0, 1 at e1, smooth in between (also works with e0 > e1)."""
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def positions(obj):
    """Vertex positions in world space as an (N, 3) array."""
    n = len(obj.data.vertices)
    co = np.empty(n * 3)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(obj.matrix_world)
    return co @ M[:3, :3].T + M[:3, 3]


def read_weights(obj, names):
    """(N, len(names)) array: weight of every vertex in every bone group."""
    W = np.zeros((len(obj.data.vertices), len(names)))
    col = {g.index: names.index(g.name) for g in obj.vertex_groups if g.name in names}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group in col:
                W[v.index, col[g.group]] = g.weight
    return W


def write_weights(obj, names, W):
    """Keep the 4 biggest weights of each vertex, normalise them to 1 and write the vertex groups."""
    W = W.copy()
    W[W < 1e-3] = 0.0
    drop = np.argsort(-W, axis=1)[:, 4:]            # everything after the 4 biggest
    np.put_along_axis(W, drop, 0.0, axis=1)
    s = W.sum(1)
    assert (s > 0).all(), f"{obj.name}: {(s == 0).sum()} vertices have no weight"
    W /= s[:, None]
    obj.vertex_groups.clear()
    for j, name in enumerate(names):
        vg = obj.vertex_groups.new(name=name)
        for i in np.nonzero(W[:, j])[0]:
            vg.add([int(i)], float(W[i, j]), "REPLACE")
    return W


def islands(obj):
    """Island id of every vertex (pieces of the mesh that are not connected by edges)."""
    n = len(obj.data.vertices)
    e = np.empty(len(obj.data.edges) * 2, dtype=np.int64)
    obj.data.edges.foreach_get("vertices", e)
    parent = list(range(n))

    def root(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in e.reshape(-1, 2).tolist():
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([root(a) for a in range(n)])


def torso_split(co):
    """Weights of Hips, Spine, Chest, Neck, Head for points of the torso, from their height.
    Joints (bone heads): Spine 1.05, Chest 1.249, Neck 1.446, Head 1.557 m; each blend is centred on one."""
    x, y, z = co[:, 0], co[:, 1], co[:, 2]
    # The neck is thin: points far from the spine axis at neck height are shoulders/collar, not neck.
    # So the neck and head blends use a height lowered by the distance beyond the neck's radius.
    r = np.hypot(x, y - 0.06)
    zn = z - np.maximum(0.0, r - 0.07)
    u1 = smoothstep(0.95, 1.17, z)    # Hips  -> Spine (wide blends: the lower back curves, no crease)
    u2 = smoothstep(1.13, 1.37, z)    # Spine -> Chest
    u3 = smoothstep(1.40, 1.50, zn)   # Chest -> Neck
    u4 = smoothstep(1.51, 1.58, zn)   # Neck  -> Head (above 1.58 the head is rigid)
    return np.stack([1 - u1, u1 * (1 - u2), u1 * u2 * (1 - u3), u1 * u2 * u3 * (1 - u4), u1 * u2 * u3 * u4], 1)


# ---------------------------------------------------------------------------------------------------
bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = bpy.data.objects["ExplorerRig"]
body = bpy.data.objects["Body"]
cloak = bpy.data.objects["Cloak"]
for o in bpy.context.view_layer.objects:
    o.select_set(False)
bpy.context.view_layer.objects.active = arm
for pb in arm.pose.bones:                           # work on (and save) the rest pose
    pb.matrix_basis.identity()

# 1) Cloak bones (re-used if the script already ran)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
for name, (par, head, tail) in CLOAK_BONES.items():
    b = eb.get(name) or eb.new(name)
    b.head, b.tail, b.roll = Vector(head), Vector(tail), 0.0
    b.parent = eb[par]
    b.use_connect = False
    b.use_deform = True
bpy.ops.object.mode_set(mode="OBJECT")
NAMES = OLD_BONES + list(CLOAK_BONES)
assert all(n in arm.data.bones for n in NAMES) and len(arm.data.bones) <= 32   # MAX_BONES in scene.vert
T = [NAMES.index(n) for n in TORSO]

# 2) Body: split each vertex's torso share by height; arms and legs keep their weights
co = positions(body)
W = read_weights(body, NAMES)
W[:, T] = W[:, T].sum(1, keepdims=True) * torso_split(co)
isl = islands(body)
for i in np.unique(isl):                            # head pieces: islands that start above the neck
    m = isl == i
    if co[m, 2].min() > 1.44:                       # (mask, eyes; the suit's collar starts lower)
        W[m] = 0.0
        W[m, NAMES.index("Head")] = 1.0
Wbody = write_weights(body, NAMES, W)

# 3) Cloak
# 3a) Copy the weights of the body underneath: average of the 8 nearest torso vertices of the body.
#     Only torso + shoulder bones: the game holds the arms and legs in a riding pose away from the
#     rest pose, so any arm/leg weight would drag the cloak with them.
ALLOWED = [NAMES.index(n) for n in TORSO + ["Shoulder.L", "Shoulder.R"]]
src = np.nonzero(Wbody[:, ALLOWED].sum(1) > 0.5)[0]
kd = kdtree.KDTree(len(src))
for k, i in enumerate(src):
    kd.insert(co[i], k)
kd.balance()
cc = positions(cloak)
Wc = np.zeros((len(cc), len(NAMES)))
for v, p in enumerate(cc):
    near = kd.find_n(p, 8)
    w = np.array([1.0 / (d + 0.01) for _, _, d in near])
    rows = Wbody[src[[k for _, k, _ in near]]][:, ALLOWED]
    Wc[v, ALLOWED] = (w[:, None] * rows).sum(0) / w.sum()

# 3b) Lower cape -> cloak bones. c = how much a vertex belongs to the cloak bones: 0 above z = 1.30,
#     1 below z = 0.85 (a long ramp, so the cape curves instead of hinging), and only behind/beside
#     the body (y > -0.08; the front of the shawl stays on the chest).
x, y, z = cc[:, 0], cc[:, 1], cc[:, 2]
c = smoothstep(1.30, 0.85, z) * smoothstep(-0.16, -0.08, y)
side = smoothstep(0.08, 0.30, np.abs(x))          # 0 = middle of the back, 1 = left/right half
Wc *= (1 - c)[:, None]
Wc[:, NAMES.index("Cloak.Back")] = c * (1 - side)
Wc[:, NAMES.index("Cloak.L")] = c * side * (x > 0)
Wc[:, NAMES.index("Cloak.R")] = c * side * (x <= 0)
write_weights(cloak, NAMES, Wc)

# 4) Save and export (same settings as the original explorer.glb: GLB, Y up, only the explorer)
bpy.ops.wm.save_mainfile(filepath=BLEND)
for o in (arm, body, cloak):
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=GLB, export_format="GLB", export_yup=True, use_selection=True,
                          export_animations=False)
print("rig_explorer: %d bones, saved %s and %s" % (len(arm.data.bones), BLEND, GLB))

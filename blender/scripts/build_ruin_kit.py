# Builds the "ancient city" ruin kit procedurally and exports one .glb per piece to assets/models/ (re-runnable):
#   blender --background --python blender/scripts/build_ruin_kit.py                 (all pieces)
#   blender --background --python blender/scripts/build_ruin_kit.py -- obelisk mastaba   (only these)
# Nothing is imported: every piece is modelled from code with bmesh (boxes, lathed columns, noisy sheets),
# then weathered (bevels, chipped corners, jagged fractures, jittered blocks) so it reads as old stone rather
# than clean CG primitives. Each piece gets ONE material whose base colour is a Poly Haven CC0 texture
# (downloaded once into assets/source/textures_<id>/), embedded in the GLB.
#
# Coordinates: every number below is in GAME / glTF axes (Y up, +Z = the piece's FRONT, metres), so they
# match the engine and the kit spec. finish() turns the result into Blender's Z-up once, just before export,
# and the glTF exporter (export_yup=True) turns it back. y = 0 is the ground line (origin, bottom-centre);
# a "skirt" continues the stone below y = 0 so the moving liquid sand never shows air under a piece.
import bpy, bmesh, math, os, sys, json, random, urllib.request
from mathutils import Vector, Matrix, noise

P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(P, "assets", "source")
OUT = os.path.join(P, "assets", "models")
UA = {"User-Agent": "ruin-kit-builder"}          # generic client name for the Poly Haven API


# ---------------------------------------------------------------- textures (Poly Haven, CC0)
def texture(tid):
    """Path of the 1k diffuse JPG of Poly Haven texture `tid`; downloads it (+ license.txt) the first time."""
    folder = os.path.join(SRC, "textures_" + tid)
    path = os.path.join(folder, tid + "_diff_1k.jpg")
    if not os.path.exists(path):
        get = lambda url: urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()
        files = json.loads(get("https://api.polyhaven.com/files/" + tid))
        info = json.loads(get("https://api.polyhaven.com/info/" + tid))
        url = files["Diffuse"]["1k"]["jpg"]["url"]
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as f:
            f.write(get(url))
        with open(os.path.join(folder, "license.txt"), "w") as f:
            f.write(f"Title: {info['name']}\nAuthor: Poly Haven ({', '.join(info.get('authors', {}))})\n"
                    f"License: CC0 1.0 Universal (public domain)\nSource: https://polyhaven.com/a/{tid}\n"
                    f"File: {url}\nDownloaded: 2026-11-27 (1k JPG diffuse only)\n")
    return path


# ---------------------------------------------------------------- small maths helpers
NOFF = Vector()                                   # per-piece noise offset, so pieces do not share patterns


def nz(p, freq=1.0):
    """Smooth noise in about [-1, 1] at point p."""
    return max(-1.0, min(1.0, noise.noise(Vector(p) * freq + NOFF)))


def nzv(p, freq=1.0):
    return noise.noise_vector(Vector(p) * freq + NOFF)


def mat4(t=(0, 0, 0), rx=0.0, ry=0.0, rz=0.0):
    """Translate * yaw(Y) * pitch(X) * roll(Z), angles in degrees: tilt the part first, then turn it."""
    R = Matrix.Rotation(math.radians(ry), 4, "Y") @ Matrix.Rotation(math.radians(rx), 4, "X") \
        @ Matrix.Rotation(math.radians(rz), 4, "Z")
    return Matrix.Translation(t) @ R


# ---------------------------------------------------------------- mesh building blocks
def new_bm():
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    return bm


def box_uv(bm, tile, off=(0.0, 0.0)):
    """Box (tri-planar) projection: each face is projected along its main axis, 1 texture tile = `tile` m."""
    uv = bm.loops.layers.uv.active
    bm.normal_update()
    for f in bm.faces:
        ax = max(range(3), key=lambda i: abs(f.normal[i]))
        a, b = {0: (2, 1), 1: (0, 2), 2: (0, 1)}[ax]
        for l in f.loops:
            l[uv].uv = (l.vert.co[a] / tile + off[0], l.vert.co[b] / tile + off[1])


def add(dst, src, M=None, tile=None, rnd=None):
    """Merge part `src` into `dst` (and free src). tile: box-project UVs first (random offset per part so
    neighbouring blocks don't show the same patch). M: 4x4 transform applied to the part."""
    if tile:
        box_uv(src, tile, (rnd.random(), rnd.random()) if rnd else (0.0, 0.0))
    if M is not None:
        bmesh.ops.transform(src, matrix=M, verts=src.verts[:])
    us, ud = src.loops.layers.uv.active, dst.loops.layers.uv.active
    vmap = {v: dst.verts.new(v.co) for v in src.verts}
    for f in src.faces:
        nf = dst.faces.new([vmap[v] for v in f.verts])
        nf.smooth = f.smooth
        for a, b in zip(f.loops, nf.loops):
            b[ud].uv = a[us].uv
    src.free()


def box(x0, x1, y0, y1, z0, z1, bevel=0.0, inset=(0.0, 0.0)):
    """Axis-aligned block. inset (ix, iz) moves the top face inwards (tapered / battered walls)."""
    bm = new_bm()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        fx, fy, fz = v.co.x + 0.5, v.co.y + 0.5, v.co.z + 0.5
        ix, iz = inset if fy > 0.5 else (0.0, 0.0)
        v.co = Vector((x0 + ix + (x1 - x0 - 2 * ix) * fx, y0 + (y1 - y0) * fy, z0 + iz + (z1 - z0 - 2 * iz) * fz))
    if bevel:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, offset_type="OFFSET", segments=1, profile=0.5,
                        affect="EDGES", clamp_overlap=True)
    return bm


def cube(sx, sy, sz, bevel=0.0):
    return box(-sx / 2, sx / 2, -sy / 2, sy / 2, -sz / 2, sz / 2, bevel)


def sheet(P, nu, nv):
    """Closed block whose two big faces are nu x nv grids: P(s, t, side) gives the point for s, t in [0, 1] on
    face side 0 or side 1, and a band of quads joins their rims. Used for everything irregular: torn slab
    undersides, jagged break faces, noisy rubble walls (P adds the noise)."""
    bm = new_bm()
    G = [[[bm.verts.new(P(i / nu, j / nv, s)) for j in range(nv + 1)] for i in range(nu + 1)] for s in (0, 1)]
    for s in (0, 1):
        for i in range(nu):
            for j in range(nv):
                q = [G[s][i][j], G[s][i + 1][j], G[s][i + 1][j + 1], G[s][i][j + 1]]
                bm.faces.new(q if s else q[::-1])
    rim = [(i, 0) for i in range(nu)] + [(nu, j) for j in range(nv)] + \
          [(i, nv) for i in range(nu, 0, -1)] + [(0, j) for j in range(nv, 0, -1)]
    for k in range(len(rim)):
        (i0, j0), (i1, j1) = rim[k], rim[(k + 1) % len(rim)]
        bm.faces.new([G[0][i0][j0], G[0][i1][j1], G[1][i1][j1], G[1][i0][j0]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def prism(pts, w0, w1, axes=(0, 1, 2)):
    """A 2D outline pts [(u, v)] extruded from w0 to w1. axes = which world axis u, v and w are."""
    def p(u, v, w):
        c = [0.0, 0.0, 0.0]
        c[axes[0]], c[axes[1]], c[axes[2]] = u, v, w
        return Vector(c)
    bm = new_bm()
    A = [bm.verts.new(p(u, v, w0)) for u, v in pts]
    B = [bm.verts.new(p(u, v, w1)) for u, v in pts]
    bm.faces.new(A)
    bm.faces.new(B[::-1])
    for k in range(len(pts)):
        bm.faces.new([A[k], A[(k + 1) % len(pts)], B[(k + 1) % len(pts)], B[k]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def lathe(rings, n, tile, top="ngon", bottom="ngon", jag=0.0, rnd=None):
    """Turned shape around the Y axis (column shafts, drums, capitals). rings: [(y, radius, flute)] from the
    bottom up; flute > 0 makes the n-gon alternate radius r and r - flute (n/2 flutes). Caps: 'ngon' (flat),
    'open' (hidden inside another part) or 'broken' (a jagged fracture: two inner rings + centre displaced
    in Y by up to +-jag, slanted, rim pulled in by 0-5 cm). UVs are cylindrical. Returns (bmesh, ring verts)."""
    bm = new_bm()
    uv = bm.loops.layers.uv.active
    circ = 2 * math.pi * max(r for _, r, _ in rings)
    R = []
    for y, r, fl in rings:
        ring = []
        for k in range(n):
            a, rr = 2 * math.pi * k / n, r - (fl if k % 2 else 0.0)
            ring.append(bm.verts.new((rr * math.cos(a), y, -rr * math.sin(a))))
        R.append(ring)
    for i in range(len(R) - 1):
        for k in range(n):
            f = bm.faces.new([R[i][k], R[i][(k + 1) % n], R[i + 1][(k + 1) % n], R[i + 1][k]])
            f.smooth = True
            # u from the ring index (k + 1 = n on the seam column), so the seam doesn't smear the texture
            for l, (kk, ii) in zip(f.loops, [(k, i), (k + 1, i), (k + 1, i + 1), (k, i + 1)]):
                l[uv].uv = (kk / n * max(1, round(circ / tile)), rings[ii][0] / tile)
    cap_faces = []
    for ring, up, mode in ((R[-1], True, top), (R[0], False, bottom)):
        if mode == "ngon":
            cap_faces.append(bm.faces.new(ring if up else ring[::-1]))
        elif mode == "broken":
            y = ring[0].co.y
            inner = [[bm.verts.new((v.co.x * s, y, v.co.z * s)) for v in ring] for s in (0.66, 0.33)]
            c = bm.verts.new((0.0, y, 0.0))
            rows = [ring] + inner
            for o, i_ in zip(rows, rows[1:]):
                for k in range(n):
                    q = [i_[k], o[k], o[(k + 1) % n], i_[(k + 1) % n]]
                    cap_faces.append(bm.faces.new(q if up else q[::-1]))
            for k in range(n):
                t = [c, inner[-1][k], inner[-1][(k + 1) % n]]
                cap_faces.append(bm.faces.new(t if up else t[::-1]))
            a = rnd.uniform(0, 2 * math.pi)                     # direction of the slant of the break
            rmax = max(r for _, r, _ in rings)
            for v in [c] + [v for row in rows for v in row]:
                slant = (v.co.x * math.cos(a) + v.co.z * math.sin(a)) / rmax
                v.co.y += jag * (0.55 * slant + 0.45 * nz(v.co, 3.0))
            for v in ring:                                       # crumbled rim: pulled in by 0-5 cm
                s = 1.0 - rnd.uniform(0.0, 0.05) / max(0.05, v.co.xz.length)
                v.co.x *= s
                v.co.z *= s
    for f in cap_faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x / tile, l.vert.co.z / tile)
    return bm, R


def torus(R0, r, y, nu=40, nv=8, tile=2.0):
    bm = new_bm()
    uv = bm.loops.layers.uv.active
    V = [[bm.verts.new(((R0 + r * math.cos(2 * math.pi * j / nv)) * math.cos(2 * math.pi * i / nu),
                        y + r * math.sin(2 * math.pi * j / nv),
                        -(R0 + r * math.cos(2 * math.pi * j / nv)) * math.sin(2 * math.pi * i / nu)))
          for j in range(nv)] for i in range(nu)]
    for i in range(nu):
        for j in range(nv):
            f = bm.faces.new([V[i][j], V[(i + 1) % nu][j], V[(i + 1) % nu][(j + 1) % nv], V[i][(j + 1) % nv]])
            f.smooth = True
            for l, (ii, jj) in zip(f.loops, [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]):
                l[uv].uv = (ii / nu * 2 * math.pi * R0 / tile, jj / nv * 2 * math.pi * r / tile)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def pyramid(half, y0, y1):
    bm = new_bm()
    b = [bm.verts.new((x * half, y0, z * half)) for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    apex = bm.verts.new((0.0, y1, 0.0))
    bm.faces.new(b)
    for k in range(4):
        bm.faces.new([b[k], b[(k + 1) % 4], apex])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def roughen(bm, amp, freq=3.0):
    """Push every vertex a little along a smooth noise field (weathered, not machine-flat)."""
    for v in bm.verts:
        v.co += nzv(v.co, freq) * amp
    return bm


# ---------------------------------------------------------------- modifiers (boolean, subsurf, decimate)
def modifiers(bm, setup):
    """Run Blender modifiers on a bmesh: setup(obj) adds them (and returns helper objects to delete)."""
    me = bpy.data.meshes.new("_tmp")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("_tmp", me)
    bpy.context.scene.collection.objects.link(ob)
    helpers = setup(ob) or []
    bpy.context.view_layer.update()
    out = bmesh.new()
    out.from_object(ob, bpy.context.evaluated_depsgraph_get())
    for o in [ob] + helpers:
        m = o.data
        bpy.data.objects.remove(o)
        bpy.data.meshes.remove(m)
    if not out.loops.layers.uv.active:
        out.loops.layers.uv.new("UVMap")
    return out


def cut(bm, cutters):
    """Exact boolean: carve the closed cutter shapes (a list of bmeshes) out of the closed part bm.
    Cutters get box UVs first so the freshly cut faces are textured too."""
    cb = new_bm()
    for c in cutters:
        add(cb, c, tile=2.0)

    def setup(ob):
        cme = bpy.data.meshes.new("_cut")
        cb.to_mesh(cme)
        cb.free()
        cob = bpy.data.objects.new("_cut", cme)
        bpy.context.scene.collection.objects.link(cob)
        m = ob.modifiers.new("cut", "BOOLEAN")
        m.object, m.operation, m.solver = cob, "DIFFERENCE", "EXACT"
        m.use_self = True                       # the part may be several overlapping blocks
        return [cob]
    return modifiers(bm, setup)


def bites(bm, points, size, rnd):
    """Chip corners/edges: a randomly turned cube of edge `size` centred on each point is cut away."""
    return cut(bm, [mat_apply(cube(size, size, size), mat4(p, rnd.uniform(20, 70), rnd.uniform(0, 90),
                                                               rnd.uniform(20, 70))) for p in points])


def mat_apply(bm, M):
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts[:])
    return bm


def rubble(dst, rnd, n, x, z, size, tile, y=None, sink=0.3):
    """n loose fallen blocks scattered in the area x=(x0, x1), z=(z0, z1), sizes in `size`=(min, max) m,
    tilted and half-sunk (y = centre height; default: sunk by `sink` of their height)."""
    for _ in range(n):
        sx, sy, sz = (rnd.uniform(*size) for _ in range(3))
        sy *= 0.7
        b = roughen(cube(sx, sy, sz, bevel=0.03), 0.02)
        yy = sy * (0.5 - sink) if y is None else y
        add(dst, b, mat4((rnd.uniform(*x), yy, rnd.uniform(*z)), rnd.uniform(-25, 25), rnd.uniform(0, 360),
                         rnd.uniform(-25, 25)), tile, rnd)


# ---------------------------------------------------------------- the city's column order
FLUTE = 0.04                                      # flute depth (20 flutes = 40-gon alternating r, r - 0.04)


def col_r(y):
    """Shaft radius at height y: 0.45 at the base (y 0.55) to 0.39 at the top (y 6.35), +1.5 cm entasis."""
    t = (y - 0.55) / 5.8
    return 0.45 - 0.06 * t + 0.015 * max(0.0, 1.0 - ((t - 1 / 3) / (2 / 3)) ** 2)


def column_base(dst, rnd, skirt, M):
    add(dst, box(-0.7, 0.7, skirt, 0.3, -0.7, 0.7, bevel=0.02), M, 2.0, rnd)      # plinth (+ foundation)
    add(dst, torus(0.55, 0.12, 0.42), M)                                           # torus base ring


def doric_column(dst, rnd, M=Matrix(), skirt=-1.5):
    column_base(dst, rnd, skirt, M)
    ys = [0.55 + 5.8 * i / 6 for i in range(7)]
    rings = [(0.45, col_r(0.55), FLUTE)] + [(y, col_r(y), FLUTE) for y in ys] + \
            [(6.35, 0.40, 0.0), (6.52, 0.565, 0.0), (6.65, 0.62, 0.0)]                  # + echinus
    shaft, _ = lathe(rings, 40, 2.0, top="open", bottom="open")
    add(dst, roughen(shaft, 0.006), M)
    abacus = box(-0.675, 0.675, 6.65, 7.0, -0.675, 0.675, bevel=0.02)
    abacus = bites(abacus, [(0.675, 7.0, 0.675), (-0.675, 7.0, -0.675)], 0.24, rnd)  # 2 chipped corners
    add(dst, abacus, M, 2.0, rnd)


def column_intact(rnd):
    bm = new_bm()
    doric_column(bm, rnd)
    return bm


def column_broken(rnd):
    bm = new_bm()
    column_base(bm, rnd, -1.5, Matrix())
    ys = [0.55, 1.5, 2.45, 3.2, 3.45]
    shaft, R = lathe([(0.45, col_r(0.55), FLUTE)] + [(y, col_r(y), FLUTE) for y in ys], 40, 2.0,
                     top="broken", bottom="open", jag=0.25, rnd=rnd)
    for a0 in (rnd.uniform(0, 3), rnd.uniform(3.2, 6.2)):        # 2 conchoidal chips just below the break
        for row, depth in ((R[-1], 0.10), (R[-2], 0.05)):
            for k, v in enumerate(row):
                d = abs((2 * math.pi * k / 40 - a0 + math.pi) % (2 * math.pi) - math.pi) * 0.45
                if d < 0.15:
                    f = 1.0 - (d / 0.15) ** 2
                    s = 1.0 - depth * f / v.co.xz.length
                    v.co.x *= s
                    v.co.z *= s
                    if row is R[-1]:
                        v.co.y -= 0.08 * f
    add(bm, roughen(shaft, 0.006))
    return bm


def drum(rnd, h, y0=0.0, chip=0.03):
    """One fluted drum (axis Y, radius 0.45) with chamfered, crumbled rims and flat ends."""
    r = 0.45
    rings = [(y0, r - 0.03, FLUTE), (y0 + 0.04, r, FLUTE), (y0 + h - 0.04, r, FLUTE), (y0 + h, r - 0.03, FLUTE)]
    bm, R = lathe(rings, 40, 2.0)
    for ring in (R[0], R[-1]):
        for v in ring:                                   # rims chipped inwards by 0-chip m (planar caps stay flat)
            s = 1.0 - chip * (0.5 + 0.5 * nz(v.co, 6.0)) / v.co.xz.length
            v.co.x *= s
            v.co.z *= s
    return bm


def column_fallen(rnd):
    bm = new_bm()
    zs = [0.15, -0.15, 0.15, -0.45]                      # alternate +-0.15; the last one rolled 0.3 m off
    for i in range(4):
        cx = -3.3 + i * 1.5 + 0.7
        yaw = 6.0 if i % 2 == 0 else -6.0
        lay = mat4((cx, 0.45, zs[i]), 0, yaw, 0) @ mat4(rz=-90) @ mat4(ry=rnd.uniform(0, 360))
        add(bm, drum(rnd, 1.4, -0.7), lay)
        add(bm, box(-0.7, 0.7, -0.4, 0.3, -0.25, 0.25), mat4((cx, 0, zs[i]), 0, yaw, 0), 2.0, rnd)   # skirt
    cap = new_bm()                                        # capital: echinus + abacus, tipped 70 deg
    ech, _ = lathe([(0.0, 0.40, 0.0), (0.15, 0.565, 0.0), (0.3, 0.62, 0.0)], 40, 2.0, top="open")
    add(cap, ech)
    add(cap, bites(box(-0.675, 0.675, 0.3, 0.65, -0.675, 0.675, bevel=0.02), [(0.675, 0.65, 0.675)], 0.24, rnd),
        tile=2.0, rnd=rnd)
    mat_apply(cap, mat4(rz=70))
    xs = [v.co.x for v in cap.verts]
    ys = [v.co.y for v in cap.verts]
    add(bm, cap, mat4((3.3 - max(xs), 1.25 - max(ys), -0.3)))     # leaning on the last drum, inside 6.6 x 1.25
    return bm


def column_drum(rnd):
    bm = drum(rnd, 0.9)
    a = rnd.uniform(0, 2 * math.pi)
    rim = (0.45 * math.cos(a), 0.9, -0.45 * math.sin(a))
    dowel = lambda y0, y1: lathe([(y0, 0.08, 0.0), (y1, 0.08, 0.0)], 12, 2.0)[0]
    bm = cut(bm, [mat_apply(cube(0.3, 0.3, 0.3), mat4(rim, 35, math.degrees(a), 40)),
                  dowel(0.8, 1.0), dowel(-0.1, 0.1)])                 # one bite + a dowel hole in each end
    return bm


def colonnade_bay(rnd):
    bm = new_bm()
    add(bm, box(-4.2, 4.2, -1.5, 0.3, -0.8, 0.8, bevel=0.02), None, 2.0, rnd)            # stylobate + skirt
    for x in (-3.0, 3.0):
        doric_column(bm, rnd, mat4((x, 0.3, 0)), skirt=0.0)
    # entablature: architrave (2 fasciae) + frieze as one block, broken off at x = +3.4 with a jagged face
    end = lambda y, z, base: base + 0.2 * nz((3.4, y, z), 2.5)
    add(bm, sheet(lambda s, t, side: Vector((end(7.3 + 0.8 * s, -0.6 + 1.2 * t, 3.4) if side else -3.9,
                                             7.3 + 0.8 * s, -0.6 + 1.2 * t)), 4, 4), None, 2.0, rnd)
    add(bm, box(-3.93, 3.15, 7.55, 7.8, -0.63, 0.63), None, 2.0, rnd)                    # projecting upper fascia
    add(bm, sheet(lambda s, t, side: Vector((end(8.1 + 0.2 * s, -0.75 + 1.5 * t, 3.2) if side else -4.05,
                                             8.1 + 0.2 * s, -0.75 + 1.5 * t)), 2, 4), None, 2.0, rnd)  # cornice
    fallen = bites(cube(1.0, 0.4, 0.6, bevel=0.02), [(0.5, 0.2, 0.3)], 0.25, rnd)
    add(bm, fallen, mat4((3.7, 0.12, 1.0), 8, 25, 20), 2.0, rnd)
    return bm


def covered(a, b, ivs):
    """Is [a, b] fully covered by the union of intervals ivs (joints of up to 2 cm allowed)?"""
    x = a
    for s, e in sorted(ivs):
        if e <= x:
            continue
        if s > x + 0.02:
            return False
        x = e
    return x >= b - 0.02


def block(dst, rnd, x0, x1, y0, y1, z0, z1, hide_top, hide_bottom, tile):
    """One ashlar block with 1 cm joints, jittered +-1.5 cm and +-1 deg; hidden top/bottom faces deleted."""
    b = box(x0 + 0.005, x1 - 0.005, y0, y1, z0 + 0.005, z1 - 0.005)
    b.normal_update()
    gone = [f for f in b.faces if (hide_top and f.normal.y > 0.9) or (hide_bottom and f.normal.y < -0.9)]
    bmesh.ops.delete(b, geom=gone, context="FACES_ONLY")
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    M = mat4((cx + rnd.uniform(-0.015, 0.015), 0, cz + rnd.uniform(-0.015, 0.015)), 0, rnd.uniform(-1, 1), 0) \
        @ Matrix.Translation((-cx, 0, -cz))
    add(dst, b, M, tile, rnd)


def wall_run(rnd):
    bm, tile = new_bm(), 2.0
    # main wall x -2.8..+5: blocks 1.0 x 0.5 x 1.2, odd courses shifted half a block
    edges = ([-2.8, -1.8, -0.8, 0.2, 1.2, 2.2, 3.2, 4.2, 5.0], [-2.8, -2.3, -1.3, -0.3, 0.7, 1.7, 2.7, 3.7, 5.0])
    counts = [9, 9, 8, 6, 5, 4, 4, 3]                     # courses per 1 m column, from -X to +X
    blocks = []
    for c in range(9):
        e = edges[c % 2]
        for x0, x1 in zip(e, e[1:]):
            n = counts[min(7, int(((x0 + x1) / 2 + 2.8) / 0.975))]
            if x0 < 0.2 and x1 > -1.4:                   # the breach notch: only 2 courses
                n = min(n, 2)
            if c < n:
                blocks.append((c, x0, x1))
    above = lambda b: [o for o in blocks if o[0] == b[0] + 1 and o[1] < b[2] - 0.01 and o[2] > b[1] + 0.01]
    for b in rnd.sample([b for b in blocks if b[0] >= 3 and not above(b)], 4):       # 4 missing top blocks
        blocks.remove(b)
    for c, x0, x1 in blocks:
        row = lambda cc: [(o[1], o[2]) for o in blocks if o[0] == cc]
        block(bm, rnd, x0, x1, 0.5 * c, 0.5 * c + 0.5, -0.6, 0.6,
              covered(x0, x1, row(c + 1)), c == 0 or covered(x0, x1, row(c - 1)), tile)
    # tower stub x -5..-2.8: 11 courses of 2 x 2 blocks (1.1 x 0.5 x 1.1), 2 top blocks missing
    missing = rnd.sample([(0, 0), (0, 1), (1, 0), (1, 1)], 2)
    for c in range(11):
        for i in range(2):
            for j in range(2):
                if c == 10 and (i, j) in missing:
                    continue
                top_hidden = c < 9 or (c == 9 and (i, j) not in missing)
                block(bm, rnd, -5 + 1.1 * i, -3.9 + 1.1 * i, 0.5 * c, 0.5 * c + 0.5, -1.1 + 1.1 * j, 1.1 * j,
                      top_hidden, True, tile)
    add(bm, box(-5.0, 5.0, -1.5, 0.0, -0.6, 0.6), None, tile, rnd)            # skirt core
    add(bm, box(-5.0, -2.8, -1.5, 0.0, -1.1, 1.1), None, tile, rnd)
    for zr, n in (((0.95, 1.7), 3), ((-1.7, -0.95), 2)):                       # fallen blocks at both feet
        for _ in range(n):
            b = cube(1.0, 0.5, 1.2) if rnd.random() < 0.5 else cube(1.2, 0.5, 1.0)
            add(bm, b, mat4((rnd.uniform(0.5, 4.5), 0.05, rnd.uniform(*zr)), rnd.choice((-1, 1)) * rnd.uniform(10, 30),
                            rnd.uniform(0, 360), rnd.choice((-1, 1)) * rnd.uniform(5, 20)), tile, rnd)
    return bm


def stump(dst, rnd, x, y, z, h, r0=0.47, r1=0.465, n=24, M=None):
    """A snapped 12-flute column stump standing at (x, y, z), h m tall, jagged top."""
    bm, _ = lathe([(y - 0.05, r0, 0.035), (y + h - 0.2, r1, 0.035), (y + h, r1, 0.035)], n, 2.0,
                  top="broken", bottom="open", jag=0.18, rnd=rnd)
    add(dst, roughen(bm, 0.006), mat4((x, 0, z)) if M is None else M)


def temple_podium(rnd):
    bm, tile = new_bm(), 4.0
    body = new_bm()                                       # FRONT = +Z; body 18 x 13, top at 2.6
    add(body, box(-9.0, 9.0, -3.0, 2.3, -6.5, 6.5))
    add(body, box(-9.12, 9.12, 2.3, 2.6, -6.62, 6.5, bevel=0.02))      # crown course (the stair covers the front)
    add(body, box(-9.15, 9.15, 0.0, 0.4, -6.65, 6.5, bevel=0.02))      # base course
    walls = [(-6, 6, -5.5, -4.5), (-6, -5, -4.5, 2), (5, 6, -4.5, 2), (-6, -1.25, 2, 3), (1.25, 6, 2, 3)]
    for x0, x1, z0, z1 in walls:                          # cella footing walls 0.8 m high, weathered tops
        add(body, sheet(lambda s, t, side, x0=x0, x1=x1, z0=z0, z1=z1: Vector((
            x0 + (x1 - x0) * s, 3.4 - 0.15 * (0.5 + 0.5 * nz((x0 + (x1 - x0) * s, 0, z0 + (z1 - z0) * t), 1.3))
            if side else 2.55, z0 + (z1 - z0) * t)), max(1, round((x1 - x0) / 1.0)), max(1, round(z1 - z0))))
    # the collapsed -X rear corner: a 4 x 4 m notch down to y = 1.2, cut with a noisy block
    notch = sheet(lambda s, t, side: Vector((-9.6 + 4.6 * s, 1.2 + 2.5 * side, -7.1 + 4.6 * t)) +
                  nzv((s * 4, side * 3, t * 4), 1.0) * 0.3, 6, 6)
    body = cut(body, [notch])
    add(bm, body, None, tile)
    for i in range(9):                                    # front stair: 9 steps, rise 0.289, run 0.35
        y0, y1, zf = (-1.5 if i == 0 else 0.289 * i), 0.289 * (i + 1), 9.65 - 0.35 * i
        if i < 2:                                         # the two lowest steps are gone for x +6..+9
            add(bm, box(-9.0, 6.0, y0, y1, 6.5, zf, bevel=0.02), None, tile, rnd)
        elif i == 2:
            add(bm, box(-9.0, 6.0, y0, y1, 6.5, zf, bevel=0.02), None, tile, rnd)
            add(bm, roughen(box(6.0, 9.0, -1.5, y1, 6.5, zf, bevel=0.02), 0.03), None, tile, rnd)
        else:
            add(bm, box(-9.0, 9.0, y0, y1, 6.5, zf, bevel=0.02), None, tile, rnd)
    for _ in range(3):                                    # loose step blocks lying in front
        add(bm, cube(1.2, 0.3, 0.35, bevel=0.02), mat4((rnd.uniform(6.3, 9.0), 0.08, rnd.uniform(10.0, 11.3)),
                                                       rnd.uniform(-20, 20), rnd.uniform(0, 360), rnd.uniform(-15, 15)),
            tile, rnd)
    rubble(bm, rnd, 8, (-10.5, -5.5), (-9.0, -6.8), (0.6, 1.2), tile)      # spilled blocks behind the notch
    for k in range(6):                                    # stumps left when the portico lifted away
        stump(bm, rnd, -7.25 + 2.9 * k, 2.6, 5.0, rnd.uniform(0.5, 1.1))
    return bm


def portico_column(dst, rnd, x, z, stub=False):
    """Portico column: radius 0.47 -> 0.41, 12 flutes, shaft y 0.6-7.2, echinus 7.2-7.5, abacus 7.5-7.8.
    stub=True: only the top 1.2 m, snapped below (it hangs from the entablature)."""
    r = lambda y: 0.47 - 0.06 * (y - 0.6) / 6.6 + 0.012 * max(0.0, 1.0 - (((y - 0.6) / 6.6 - 1 / 3) / (2 / 3)) ** 2)
    ys = [6.6, 7.2] if stub else [0.55, 2.25, 3.9, 5.55, 7.2]
    rings = [(y, r(y), 0.035) for y in ys] + [(7.2, 0.42, 0.0), (7.37, 0.555, 0.0), (7.5, 0.6, 0.0)]
    bm, _ = lathe(rings, 24, 2.0, top="open", bottom="broken" if stub else "open", jag=0.2, rnd=rnd)
    add(dst, roughen(bm, 0.006), mat4((x, 0, z)))
    add(dst, bites(box(x - 0.62, x + 0.62, 7.5, 7.8, z - 0.62, z + 0.62, bevel=0.02),
                   [(x + rnd.choice((-0.62, 0.62)), 7.8, z + 0.62)], 0.2, rnd), None, 2.0, rnd)


def temple_portico(rnd):
    bm, tile = new_bm(), 2.0                              # FRONT = +Z; origin = bottom of the undisplaced slab
    under = lambda x, z: -0.9 * max(0.0, min(1.0, 0.45 + 0.6 * nz((x, 0, z), 0.35) + 0.15 * nz((x, 0, z), 1.3)))
    add(bm, sheet(lambda s, t, side: Vector((-8.2 + 16.4 * s, 0.6 if side else under(-8.2 + 16.4 * s, -2.2 + 4.4 * t),
                                             -2.2 + 4.4 * t)), 16, 4), None, tile, rnd)   # torn stylobate slab
    for _ in range(6):                                    # block fragments hanging from the torn underside
        x, z, s = rnd.uniform(-7.2, 7.2), rnd.uniform(-1.6, 1.6), rnd.uniform(0.5, 1.0)
        add(bm, roughen(cube(s, s * 0.8, s * rnd.uniform(0.7, 1.0), bevel=0.03), 0.02),
            mat4((x, under(x, z) - 0.3 * s, z), rnd.uniform(-25, 25), rnd.uniform(0, 360), rnd.uniform(-25, 25)),
            tile, rnd)
    for k in range(5):                                    # 5 columns; the 6th (+X corner) is only a stub
        portico_column(bm, rnd, -7.25 + 2.9 * k, 1.0)
    portico_column(bm, rnd, 7.25, 1.0, stub=True)
    # entablature (z -1.6..+1.2): architrave, frieze, cornice, broken off towards +X at different places
    def beam(y0, y1, z0, z1, xa, xb, nu=3, nv=4):
        return sheet(lambda s, t, side: Vector((xb + 0.25 * nz((xb, y0 + (y1 - y0) * s, z0 + (z1 - z0) * t), 2.0)
                                                if side else xa, y0 + (y1 - y0) * s, z0 + (z1 - z0) * t)), nu, nv)
    add(bm, beam(7.8, 8.5, -1.6, 1.2, -8.2, 7.6), None, tile, rnd)        # architrave runs on over the stub
    add(bm, beam(8.5, 9.0, -1.6, 1.2, -8.2, 6.8), None, tile, rnd)        # frieze
    add(bm, beam(9.0, 9.4, -1.8, 1.4, -8.4, 6.3, 2), None, tile, rnd)     # cornice, projecting 0.2
    for i in range(8):                                    # triglyphs protruding 3 cm from the frieze
        x = -7.6 + 1.85 * i
        add(bm, box(x - 0.22, x + 0.22, 8.53, 8.97, 1.19, 1.23), None, tile, rnd)
    # pediment: tympanum (recessed 0.15) with its apex broken off and its right third collapsed
    rake = lambda x: 9.4 + 2.4 * (x + 8.2) / 8.2
    tymp = [(-8.2, 9.4), (-3.42, rake(-3.42)), (-2.7, 10.55), (-1.8, 10.72), (-0.9, 10.45), (0.1, 10.62),
            (1.0, 10.3), (1.9, 10.42), (2.7, 10.05), (3.1, 9.85), (2.95, 9.65), (3.5, 9.5), (3.9, 9.4)]
    add(bm, prism(tymp, -1.6, 1.05), None, tile, rnd)
    # left raking cornice (0.25 m thick, projecting 0.2), ending in a slanted break below the lost apex
    add(bm, prism([(-8.45, rake(-8.45) - 0.02), (-3.42, rake(-3.42)), (-3.55, rake(-3.55) + 0.14),
                   (-3.75, rake(-3.75) + 0.26), (-8.45, rake(-8.45) + 0.24)], -1.8, 1.25), None, tile, rnd)
    # back wall (cella front) 0.4 thick at z = -1.8, y 0.6-7.8, with a 2.5 x 5 m doorway at x = 0
    add(bm, box(-8.0, -1.25, 0.6, 7.8, -2.0, -1.6, bevel=0.02), None, tile, rnd)
    add(bm, box(-1.25, 1.25, 5.6, 7.8, -2.0, -1.6, bevel=0.02), None, tile, rnd)
    add(bm, sheet(lambda s, t, side: Vector((7.0 + 0.35 * nz((7, 0.6 + 7.2 * s, t), 1.5) if side else 1.25,
                                             0.6 + 7.2 * s, -2.0 + 0.4 * t)), 6, 1), None, tile, rnd)
    return bm


def rough_wall(x0, z0, x1, z1, thick, height, amp=0.05, step=0.5, nv=5):
    """Rubble-stone wall from (x0, z0) to (x1, z1) on the ground plan, from y = -1.5 (skirt) up to
    height(s) (s = 0..1 along it), its surface pushed around by `amp` m of smooth noise."""
    d = Vector((x1 - x0, z1 - z0))
    n = Vector((-d.y, d.x)).normalized()
    def P(s, t, side):
        x, z = x0 + d.x * s + n.x * (side - 0.5) * thick, z0 + d.y * s + n.y * (side - 0.5) * thick
        p = Vector((x, -1.5 + t * (height(s) + 1.5), z))
        return p + nzv(p, 1.7) * amp
    return sheet(P, max(2, round(d.length / step)), nv)


def house_ruin(rnd):
    bm, tile = new_bm(), 2.0                              # OPEN FRONT = +Z; footprint 6 x 5, walls 0.7 thick
    jag = lambda base, a, f=6.0, off=0.0: (lambda s: base + a * nz((s * f + off, 0.3, 1.7), 1.0))
    back = rough_wall(-3.0, -2.15, 3.0, -2.15, 0.7, lambda s: min(2.8, jag(2.55, 0.3)(s)), nv=6)
    back = cut(back, [box(1.2, 1.8, 1.6, 2.2, -2.8, -1.5)])               # window notch
    add(bm, back, None, tile, rnd)
    for x in (-2.65, 2.65):                               # side walls stepping down 2.8 -> 0.8 towards +Z
        for i in range(4):
            za, zb = -1.8 + 4.3 * i / 4, -1.8 + 4.3 * (i + 1) / 4
            add(bm, rough_wall(x, za, x, zb, 0.7, jag(2.8 - i * 2.0 / 3 - 0.1, 0.1, 3.0, x + i), nv=4),
                None, tile, rnd)
    add(bm, rough_wall(-2.3, 2.15, -0.7, 2.15, 0.7, jag(0.75, 0.06), nv=3), None, tile, rnd)    # front stubs
    add(bm, rough_wall(0.7, 2.15, 2.3, 2.15, 0.7, jag(1.12, 0.08, 6.0, 4.0), nv=3), None, tile, rnd)
    rubble(bm, rnd, 8, (-1.9, 1.9), (-1.4, 1.4), (0.4, 0.8), tile)        # fallen stones inside
    add(bm, roughen(cube(1.6, 0.35, 0.5, bevel=0.03), 0.015), mat4((0.1, 0.1, 3.0), 4, 12, -6), tile, rnd)
    return bm


def mastaba(rnd):
    bm, tile = new_bm(), 3.0
    inset = 3.2 * math.tan(math.radians(10))              # walls battered 10 deg inwards
    base = new_bm()
    add(base, box(-3.5, 3.5, 0.0, 3.2, -2.25, 2.25, bevel=0.03, inset=(inset, inset)))
    niches = []
    for side in (1, -1):                                  # false-door niche on both long faces (+-Z)
        face = mat4((0, 0.25, side * (2.25 - 0.25 * math.tan(math.radians(10)))), -10 * side, 0, 0)
        niches.append(mat_apply(box(-0.45, 0.45, 0.0, 1.8, -0.25 if side > 0 else -0.6, 0.6 if side > 0 else 0.25), face))
        add(bm, box(-0.6, 0.6, 1.85, 2.15, -0.12 if side > 0 else -0.04, 0.04 if side > 0 else 0.12, bevel=0.02),
            face, tile, rnd)                              # lintel slab above it
    add(bm, cut(base, niches), None, tile)
    add(bm, box(-3.5, 3.5, -2.0, 0.0, -2.25, 2.25), None, tile, rnd)        # skirt
    collapse = sheet(lambda s, t, side: Vector((0.8 + 1.8 * s, 3.75 + 1.3 * side, 0.05 + 1.8 * t)) +
                     nzv((s * 3, side * 3, t * 3), 1.0) * 0.18, 3, 3)     # a ragged 1.2 m bite out of the corner
    tier = cut(box(-2.0, 2.0, 3.2, 4.4, -1.25, 1.25, bevel=0.03), [collapse])
    add(bm, tier, None, tile, rnd)                        # second tier, +X corner collapsed
    rubble(bm, rnd, 3, (1.2, 2.7), (-1.5, 1.5), (0.6, 0.9), tile, y=3.45)  # loose blocks on the roof
    rubble(bm, rnd, 1, (3.8, 4.6), (-1.0, 1.0), (0.6, 0.9), tile)          # and 2 at the foot
    rubble(bm, rnd, 1, (-4.4, -3.8), (0.5, 2.6), (0.6, 0.9), tile)
    return bm


def sarcophagus(rnd):
    bm, tile = new_bm(), 2.0
    add(bm, box(-1.5, 1.5, -1.0, 0.4, -0.75, 0.75, bevel=0.02), None, tile, rnd)      # plinth + skirt
    chest = box(-1.3, 1.3, 0.4, 1.4, -0.55, 0.55, bevel=0.02)
    panels = [box(-1.18, 1.18, 0.52, 1.28, 0.53, 0.7), box(-1.18, 1.18, 0.52, 1.28, -0.7, -0.53),
              box(1.28, 1.45, 0.52, 1.28, -0.43, 0.43), box(-1.45, -1.28, 0.52, 1.28, -0.43, 0.43)]
    add(bm, cut(chest, [box(-1.12, 1.12, 0.6, 1.6, -0.37, 0.37)] + panels), None, tile, rnd)   # hollow + panels
    lid = new_bm()                                        # gabled lid 2.7 x 0.45 x 1.2 with 4 acroteria
    add(lid, box(-1.35, 1.35, 0.0, 0.2, -0.6, 0.6, bevel=0.02))
    add(lid, prism([(-0.58, 0.19), (0.58, 0.19), (0.0, 0.45)], -1.33, 1.33, axes=(2, 1, 0)))
    for x in (-1.25, 1.25):
        for z in (-0.5, 0.5):
            add(lid, box(x - 0.1, x + 0.1, 0.15, 0.4, z - 0.1, z + 0.1, bevel=0.015))
    lid = cut(lid, [mat_apply(cube(0.55, 0.8, 0.55), mat4((1.35, 0.2, 0.6), 0, 45, 0))])   # broken corner
    add(bm, lid, mat4((0.5, 1.4, 0.0), 0, 7, 0), tile, rnd)           # slid 0.5 m to +X and turned 7 deg
    add(bm, roughen(cube(0.4, 0.3, 0.35, bevel=0.02), 0.02), mat4((2.0, 0.1, 0.55), 15, 30, 25), tile, rnd)
    return bm


def obelisk(rnd):
    bm, tile = new_bm(), 3.0
    add(bm, box(-1.3, 1.3, -2.0, 0.5, -1.3, 1.3), None, tile, rnd)        # base step 1 + skirt
    add(bm, box(-1.0, 1.0, 0.5, 1.0, -1.0, 1.0), None, tile, rnd)         # base step 2
    shaft = box(-0.55, 0.55, 1.0, 12.0, -0.55, 0.55, inset=(0.2, 0.2))   # 11 m, 1.1 -> 0.7 m square
    shaft = cut(shaft, [mat_apply(box(-0.085, 0.085, -0.75, 0.75, -0.085, 0.085), mat4((0.45, 6.5, 0.45), 0, 45, 0))])
    add(bm, shaft, None, tile, rnd)                       # one arris chipped along 1.5 m at mid-height
    add(bm, pyramid(0.35, 12.0, 12.8), None, tile, rnd)   # pyramidion
    return bm


def monolith(rnd):
    bm = box(-0.7, 0.7, -1.5, 4.8, -0.35, 0.35, inset=(0.25, 0.1))       # 1.4 x 0.7 -> 0.9 x 0.5, broad faces +-Z
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=True)

    def subsurf(ob):
        ob.modifiers.new("s", "SUBSURF").levels = 2
    bm = modifiers(bm, subsurf)                           # rounded, uneven top
    bm.normal_update()
    for v in bm.verts:                                    # clouds-like noise, strength 0.08 (+ a finer octave)
        v.co += v.normal * (0.08 * nz(v.co, 1.2) + 0.025 * nz(v.co, 4.0))
    lo, hi = min(v.co.y for v in bm.verts), max(v.co.y for v in bm.verts)
    for v in bm.verts:                                    # back to exactly y -1.5 .. 4.8
        v.co.y = -1.5 + (v.co.y - lo) * 6.3 / (hi - lo)
    tris = sum(len(f.verts) - 2 for f in bm.faces)

    def decimate(ob):
        ob.modifiers.new("d", "DECIMATE").ratio = 640 / tris
    bm = modifiers(bm, decimate)
    for k in range(9):                                    # 4 carved V-grooves (0.05 deep) between y 3.0 and 3.4
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-4,
                               plane_co=(0, 3.0 + 0.05 * k, 0), plane_no=(0, 1, 0))
    bm.normal_update()
    for v in bm.verts:
        if any(abs(v.co.y - g) < 1e-3 for g in (3.05, 3.15, 3.25, 3.35)):
            h = Vector((v.normal.x, 0, v.normal.z))
            if h.length > 0.3:
                v.co -= h.normalized() * 0.05
    for f in bm.faces:
        f.smooth = True
    box_uv(bm, 2.0)
    return bm


def step_pyramid(rnd):
    bm, tile = new_bm(), 4.0                              # FRONT = +Z; 6 tiers of 3.6 m, 44 m base, inset 3.4
    for k in range(5):
        w = 44 - 6.8 * k
        tier = box(-w / 2, w / 2, -4.0 if k == 0 else 3.6 * k, 3.6 * (k + 1), -w / 2, w / 2)
        cx, cz = rnd.choice((-1, 1)) * w / 2, rnd.choice((-1, 1)) * w / 2
        add(bm, bites(tier, [(cx, 3.6 * (k + 1), cz)], rnd.uniform(2.5, 4.0), rnd), None, tile, rnd)   # worn corner
    # tier 6 (y 18-21.6): only its -X third still stands, with a jagged broken face; the rest is a rubble heap
    add(bm, sheet(lambda s, t, side: Vector((-1.67 + 0.6 * nz((0, 18 + 3.6 * s, -5 + 10 * t), 0.6) if side else -5.0,
                                             18 + 3.6 * s, -5 + 10 * t)), 4, 5), None, tile, rnd)
    add(bm, sheet(lambda s, t, side: Vector((-2.0 + 7.0 * s, 18.3 + 0.6 * (0.5 + 0.5 * nz((s * 7, 0, t * 10), 0.5)) - 0.1
                                             if side else 17.9, -5 + 10 * t)), 5, 5), None, tile, rnd)
    rubble(bm, rnd, 5, (-7.0, 7.0), (-7.5, 7.5), (1.5, 3.0), tile, y=18.4)     # fallen blocks on tier 5
    rubble(bm, rnd, 5, (-24.0, 24.0), (23.0, 26.0), (1.5, 3.0), tile)          # and at the foot
    for i in range(40):                                   # 6 m wide staircase up the +Z face to y = 18
        zf = 25.7 - 0.425 * i
        add(bm, box(-3.0, 3.0, -4.0 if i == 0 else 0.45 * i, 0.45 * (i + 1), zf - 3.5, zf), None, tile, rnd)
    return bm


# ---------------------------------------------------------------- export
PIECES = {
    # name: (builder, Poly Haven texture id, max triangles)
    "column_intact":  (column_intact,  "old_sandstone_02",          3000),
    "column_broken":  (column_broken,  "old_sandstone_02",          2500),
    "column_fallen":  (column_fallen,  "old_sandstone_02",          2500),
    "column_drum":    (column_drum,    "old_sandstone_02",           600),
    "colonnade_bay":  (colonnade_bay,  "old_sandstone_02",          7000),
    "wall_run":       (wall_run,       "sandstone_cracks",          3500),
    "temple_podium":  (temple_podium,  "large_sandstone_blocks_01", 5000),
    "temple_portico": (temple_portico, "old_sandstone_02",         12000),
    "house_ruin":     (house_ruin,     "rabdentse_ruins_wall",      3000),
    "mastaba":        (mastaba,        "large_sandstone_blocks",    1500),
    "sarcophagus":    (sarcophagus,    "old_sandstone_02",          1200),
    "obelisk":        (obelisk,        "sandstone_cracks",           400),
    "monolith":       (monolith,       "sandstone_cracks",          1500),
    "step_pyramid":   (step_pyramid,   "large_sandstone_blocks",    3000),
}
MATERIALS = {}


def material(tid):
    """One material per texture: Principled BSDF, base colour = the (embedded) diffuse JPG, matte."""
    if tid not in MATERIALS:
        img = bpy.data.images.load(texture(tid), check_existing=True)
        if max(img.size) > 1024:
            img.scale(1024, 1024)
        mat = bpy.data.materials.new(tid)
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Roughness"].default_value = 0.95
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        MATERIALS[tid] = mat
    return MATERIALS[tid]


def finish(name, bm, tid, budget):
    ys = [v.co.y for v in bm.verts]
    # game Y-up -> Blender Z-up: (x, y, z) -> (x, -z, y), so the front (+Z) becomes Blender -Y
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"), verts=bm.verts[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    me.materials.append(material(tid))
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    assert tris <= budget, f"{name}: {tris} triangles > budget {budget}"
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + ".glb"), export_format="GLB",
                              export_yup=True, use_selection=True)
    print(f"KIT {name}: {tris} tris, y {min(ys):.2f} .. {max(ys):.2f} m, texture {tid}")
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(me)


bpy.ops.wm.read_factory_settings(use_empty=True)
wanted = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else list(PIECES)
for name in wanted:
    build, tid, budget = PIECES[name]
    rnd = random.Random(name)                             # same piece name -> same stones on every run
    NOFF = Vector((rnd.uniform(0, 100), rnd.uniform(0, 100), rnd.uniform(0, 100)))
    finish(name, build(rnd), tid, budget)

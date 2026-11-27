#version 330 core
in vec3 vWorldPos;
in vec3 vLocalPos;
in vec3 vNormal;
in vec2 vUV;
in vec3 vDiff;               // Gouraud lighting from the vertex shader
in vec3 vSpec;
in float vHighlight;         // skinned vertices moved by the selected bones

// Textures (texture units are set once in main.cpp)
uniform sampler2D uTex;          // unit 0: the model's own base-colour texture (from the .glb)
uniform sampler2D uSandTex;      // unit 2: sand colour, tiled over the ground
uniform sampler2D uSandNormal;   // unit 3: sand normal map (tangent space, OpenGL convention)
uniform sampler2D uGalaxy;       // unit 4: Milky Way panorama (equirectangular), seen through the cracked dome
uniform bool uHasTex;            // this mesh has a texture
uniform bool uUseTex, uUseNormalMap;   // F6 / F7 toggles
uniform mat3 uSkyRot;            // slowly turns the galaxy behind the dome

uniform vec4 uColor;
uniform vec3 uEmissive;
uniform float uDissolve;     // ruins: 0 = solid, 1 = fully turned to dust
uniform bool uHighlight;     // part of the joint subtree selected in joint mode
uniform float uTime;
const int MAX_RIPPLES = 24;
uniform vec4 uRipples[MAX_RIPPLES];   // footstep ripples (see scene.vert); glow evaluated per pixel so rings stay sharp

out vec4 FragColor;

const vec3 HORIZON = vec3(1.00, 0.55, 0.30);   // sunset orange
const vec3 ZENITH  = vec3(0.16, 0.10, 0.28);   // dusky violet
const vec3 GLOW    = vec3(0.30, 0.85, 1.00);   // bioluminescent cyan (ripples, lantern)
const vec3 FIRE    = vec3(1.00, 0.42, 0.10);   // glowing edge of a dissolving ruin
const float PI = 3.14159265;

// ---- small noise toolkit ----
float hash(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float noise(vec3 x) {
    vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 5; ++i) { s += a * noise(p); p *= 2.03; a *= 0.5; } return s; }
// Distance to the nearest cell border of a 3D Voronoi pattern (the glass cracks)
float crackDist(vec3 p) {
    vec3 ip = floor(p), fp = fract(p);
    float d1 = 8.0, d2 = 8.0;
    for (int k = -1; k <= 1; ++k) for (int j = -1; j <= 1; ++j) for (int i = -1; i <= 1; ++i) {
        vec3 g = vec3(i, j, k), o = vec3(hash(ip + g), hash(ip + g + 7.1), hash(ip + g + 13.7));
        float d = length(g + o - fp);
        if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d;
    }
    return d2 - d1;
}

// Bright rings travelling outwards from each footstep, fading as they spread
float rippleGlow(vec2 p) {
    float g = 0.0;
    for (int i = 0; i < MAX_RIPPLES; ++i) {
        vec4 r = uRipples[i];
        float age = uTime - r.z;
        if (r.w <= 0.0 || age < 0.0 || age > 5.0) continue;
        float d = distance(p, r.xy), front = 1.8 * age;
        float rings = 0.0;
        for (int k = 0; k < 3; ++k)                                   // three concentric rings per step
            rings += exp(-pow((d - front + 0.45 * float(k)) / 0.07, 2.0)) * (1.0 - 0.3 * float(k));
        g += rings * exp(-0.9 * age) * r.w + 0.25 * exp(-d * 2.0) * exp(-2.0 * age);   // + glow at the footprint
    }
    return min(g, 1.5);
}

// [Texture mapping: galaxy (equirectangular)] Galaxy image lookup by direction.
// u = longitude around the vertical axis, v = latitude. textureLod(.., 0) avoids a mip seam where u wraps 1 -> 0.
vec3 galaxyColor(vec3 dir) {
    if (!uUseTex) return vec3(0.0);
    vec3 d = uSkyRot * dir;
    vec2 uv = vec2(atan(d.z, d.x) / (2.0 * PI) + 0.5, asin(clamp(d.y, -1.0, 1.0)) / PI + 0.5);
    return textureLod(uGalaxy, uv, 0.0).rgb;
}

// ---- sky: sunset gradient seen through a cracked glass dome, with the galaxy behind the cracks ----
vec3 skyColor(vec3 dir) {
    float h = clamp(dir.y, 0.0, 1.0);
    vec3 c = mix(HORIZON, ZENITH, pow(h, 0.55));
    vec3 sd = normalize(uSunDir);
    float sun = max(dot(dir, sd), 0.0);
    c += uSunColor * (pow(sun, 900.0) * 6.0 + pow(sun, 30.0) * 0.6 + pow(sun, 4.0) * 0.25);   // disc + corona + haze

    float high = smoothstep(0.04, 0.35, dir.y);
    if (high <= 0.0) return c;                                          // near the horizon: only the sunset
    vec3 galaxy = galaxyColor(dir) * 1.6;
    c = mix(c, c * 0.45 + galaxy, 0.65 * high);                         // the dome is tinted glass

    // Cracks: thin bright lines where light leaks through, plus a soft golden halo around them
    float cd = crackDist(dir * 4.0 + vec3(1.7));
    float line = 1.0 - smoothstep(0.0, 0.035, cd);
    float halo = 1.0 - smoothstep(0.0, 0.25, cd);
    c += high * (line * (galaxy * 2.5 + vec3(1.0, 0.85, 0.55) * 0.9) + halo * vec3(1.0, 0.7, 0.35) * 0.12);
    return c;
}

void main() {
    if (uMode == MODE_SKY) {
        FragColor = vec4(skyColor(normalize(vWorldPos - uCamPos)), 1.0);
        return;
    }
    if (uMode == MODE_OVERLAY) {                 // skeleton overlay: flat colour
        FragColor = uColor;
        return;
    }

    // [Advanced: noise dissolve (ruins form / crumble)]
    // Each fragment gets a fixed value k in [0,1]: 3D noise of its model-space position, mixed with its
    // height so the top crumbles first and the base forms first. Fragments with k below the threshold
    // are discarded (a hole), the ones just above it glow like embers.
    float edge = 0.0;
    if (uDissolve > 0.0) {
        float nz = clamp((fbm(vLocalPos * 1.6) - 0.25) / 0.5, 0.0, 1.0);
        float k = mix(nz, 1.0 - clamp(vLocalPos.y / 6.0, 0.0, 1.0), 0.35);
        if (k < uDissolve) discard;
        edge = 1.0 - smoothstep(0.0, 0.08, k - uDissolve);
    }
    if (uShadowPass) return;          // shadow map: only depth is needed (the discard above also cuts the shadow)

    vec3 n = normalize(vNormal);
    if (uShading == 2)                // flat: one normal per triangle, from the screen-space derivatives
        n = normalize(cross(dFdx(vWorldPos), dFdy(vWorldPos)));
    vec3 v = normalize(uCamPos - vWorldPos);
    vec3 base;
    vec3 emissive = uEmissive + FIRE * 2.5 * edge;

    if (uMode == MODE_SAND) {
        // [Advanced: liquid sand] surface colour
        vec3 p = vec3(vUV.x, 0.0, vUV.y);                             // vUV = world xz position (metres)
        vec3 tint = mix(vec3(0.78, 0.47, 0.26), vec3(0.95, 0.70, 0.44), fbm(p * 0.05));   // large-scale colour patches
        if (uUseTex) {
            // [Texture mapping: tiled sand + normal map] UV = world xz / 7, so the 2K image covers 7 x 7 m and GL_REPEAT tiles it.
            // A second, 4x larger sample is mixed in so the repetition is not visible from far away.
            vec2 uv = vUV / 7.0 + uTime * vec2(0.012, 0.005);         // the texture drifts: the sand flows
            vec3 tex = mix(texture(uSandTex, uv).rgb, texture(uSandTex, uv * 0.23 + 0.37).rgb, 0.4);
            base = tex * tint * 2.0;
            if (uUseNormalMap && uShading == 0) {
                // Normal mapping: the image stores a normal in tangent space (x along u, y along v, z out of
                // the surface). Build that frame (TBN) on the moving sand and rotate the stored normal into world.
                vec3 T = normalize(vec3(1.0, 0.0, 0.0) - n * n.x);      // u runs along world +x, made perpendicular to n
                vec3 B = cross(T, n);                                   // v runs along world +z
                vec3 m = texture(uSandNormal, uv).xyz * 2.0 - 1.0;      // [0,1] colour -> [-1,1] vector
                n = normalize(mat3(T, B, n) * vec3(m.xy * 1.5, m.z));   // 1.5 = bump strength
            }
        } else {
            base = tint;
        }
        float sparkle = step(0.996, hash(floor(p * 35.0))) * pow(max(dot(reflect(-normalize(uSunDir), n), v), 0.0), 24.0);
        emissive += GLOW * (rippleGlow(vUV) * 0.8 + 0.03 * smoothstep(0.6, 1.0, noise(p * 0.3 + uTime * 0.2)));
        emissive += vec3(1.0, 0.9, 0.7) * sparkle * 0.8;
    } else {
        // [Texture mapping: model UVs] glTF base colour = texture (sampled with the model's own UVs) x colour factor
        base = (uHasTex && uUseTex) ? texture(uTex, vUV).rgb * uColor.rgb : uColor.rgb;
    }

    // Ambient: hemispheric (cool sky light from above, warm sand bounce from below)
    vec3 color = mix(vec3(0.22, 0.13, 0.09), vec3(0.24, 0.22, 0.40), n.y * 0.5 + 0.5) * base;

    // [Shading: Phong / Gouraud / flat] Diffuse + specular: from the vertex shader (Gouraud) or per pixel here
    vec3 diff = vDiff, spec = vSpec;
    if (uShading != 1)
        lightAt(vWorldPos, n, specOf(), shineOf(), diff, spec);
    color += base * diff + spec + emissive;
    float hl = uHighlight ? 1.0 : (uSkinned ? vHighlight : 0.0);
    color += hl * vec3(0.15, 0.45, 0.6) * (0.6 + 0.4 * sin(uTime * 6.0));   // pulse the selected joint's subtree

    // Distance fog blends into the sky colour at the horizon (hides the edge of the ground)
    float dist = length(uCamPos - vWorldPos);
    float fog = 1.0 - exp(-pow(dist * 0.006, 1.5));
    color = mix(color, skyColor(normalize(vec3(-v.x, 0.02, -v.z))), clamp(fog, 0.0, 1.0));

    FragColor = vec4(color, 1.0);
}

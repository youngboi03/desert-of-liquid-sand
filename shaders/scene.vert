#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aUV;
layout(location = 3) in ivec4 aBones;  // skinning: indices of up to 4 bones
layout(location = 4) in vec4 aWeights; // and their weights

uniform mat4 uModel;
const int MAX_BONES = 32;
uniform mat4 uBones[MAX_BONES];   // bone world matrix * inverse bind matrix, from the node hierarchy
uniform float uBoneHighlight[MAX_BONES];   // joint mode: 1 for bones in the selected subtree
uniform mat4 uView;
uniform mat4 uProj;
uniform float uTime;

const int MAX_RIPPLES = 24;
uniform vec4 uRipples[MAX_RIPPLES];   // xz = origin, z = start time, w = strength (0 = unused)

out vec3 vWorldPos;
out vec3 vLocalPos;         // model-space position (the dissolve noise is fixed to the model)
out vec3 vNormal;
out vec2 vUV;
out vec3 vDiff;             // Gouraud: lighting computed here per vertex and interpolated
out vec3 vSpec;
out float vHighlight;

// [Advanced: liquid sand] Sand height. MUST match sandHeight() in src/sand.h (the camel walks on it).
float dunes(vec2 p) {
    float corridor = smoothstep(4.0, 16.0, abs(p.y - 8.0 * sin(p.x / 25.0)));   // flat lane along the trail z = 8 sin(x/25)
    vec2 q = p + 6.0 * vec2(sin(p.y * 0.031), sin(p.x * 0.027));     // warp so the ridges meander
    float d = 2.2 * (1.0 - abs(sin(q.x * 0.045 + q.y * 0.020))) +
              1.3 * (1.0 - abs(sin(q.y * 0.060 - q.x * 0.025)));       // 1-|sin| = sharp dune crests
    return corridor * d * 1.6;
}
float waves(vec2 p, float t) {   // the sand moves like a slow sea swell
    return 0.45 * sin(dot(p, vec2(0.10, 0.06)) - 0.6 * t) +
           0.30 * sin(dot(p, vec2(0.28, 0.10)) - 1.1 * t) +
           0.18 * sin(dot(p, vec2(-0.12, 0.31)) - 0.8 * t + 1.3) +
           0.07 * sin(dot(p, vec2(0.60, 0.50)) - 1.9 * t);
}
// Concentric ripples from the camel's footsteps (not on the CPU: too small to change the walking height)
float ripples(vec2 p, float t) {
    float h = 0.0;
    for (int i = 0; i < MAX_RIPPLES; ++i) {
        vec4 r = uRipples[i];
        float age = t - r.z;
        if (r.w <= 0.0 || age < 0.0 || age > 5.0) continue;
        float d = distance(p, r.xy), front = 1.8 * age;
        float ring = exp(-pow((d - front) / 0.35, 2.0)) * exp(-0.9 * age) * r.w;
        h += 0.10 * ring * sin(7.0 * (d - front));
    }
    return h;
}
float sandHeight(vec2 p, float t) {
    return dunes(p) + waves(p, t) + ripples(p, t);
}

void main() {
    vUV = aUV;
    vLocalPos = aPos;
    vHighlight = uSkinned ? dot(aWeights, vec4(uBoneHighlight[aBones.x], uBoneHighlight[aBones.y],
                                               uBoneHighlight[aBones.z], uBoneHighlight[aBones.w])) : 0.0;
    if (uMode == MODE_SAND) {
        vec2 p = (uModel * vec4(aPos, 1.0)).xz;
        float e = 0.2;
        float h = sandHeight(p, uTime);
        vec3 n = vec3(sandHeight(p - vec2(e, 0), uTime) - sandHeight(p + vec2(e, 0), uTime), 2.0 * e,
                      sandHeight(p - vec2(0, e), uTime) - sandHeight(p + vec2(0, e), uTime));
        vWorldPos = vec3(p.x, h, p.y);
        vNormal = normalize(n);
        vUV = p;
    } else {
        // [Advanced: skinning + scene graph] Linear blend skinning: each vertex follows a weighted mix of
        // up to 4 bones (uBones come from the node hierarchy)
        mat4 M = uSkinned ? aWeights.x * uBones[aBones.x] + aWeights.y * uBones[aBones.y] +
                            aWeights.z * uBones[aBones.z] + aWeights.w * uBones[aBones.w]
                          : uModel;
        vWorldPos = (M * vec4(aPos, 1.0)).xyz;
        vNormal = mat3(transpose(inverse(M))) * aNormal;
    }
    // [Shading: Phong / Gouraud / flat] Gouraud: evaluate the lights once per vertex; the rasteriser
    // interpolates the result
    vDiff = vec3(0.0); vSpec = vec3(0.0);
    if (uShading == 1 && (uMode == MODE_OBJECT || uMode == MODE_SAND) && !uShadowPass)
        lightAt(vWorldPos, normalize(vNormal), specOf(), shineOf(), vDiff, vSpec);
    gl_Position = uProj * uView * vec4(vWorldPos, 1.0);   // shadow pass: uView/uProj = the sun's camera
}

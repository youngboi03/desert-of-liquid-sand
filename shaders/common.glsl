// Shared by scene.vert and scene.frag (inserted after the #version line by createProgram).
// Lighting lives here so the same Blinn-Phong code can run per vertex (Gouraud) or per pixel (Phong / flat).

uniform vec3 uCamPos;
uniform int uMode;            // what is being drawn (must match DrawMode in main.cpp):
const int MODE_OBJECT = 0, MODE_SKY = 1, MODE_SAND = 2, MODE_OVERLAY = 3;   // lit model, sky, liquid sand, skeleton lines
uniform bool uSkinned;        // mesh deformed by a skeleton (see scene.vert)
uniform int uShading;         // 0 = Phong (per pixel), 1 = Gouraud (per vertex), 2 = flat (per face)
uniform float uSpec;          // material specular coefficient ks
uniform float uShininess;     // material shininess (Blinn-Phong exponent)

// ---- Light 1: directional sun (low sunset sun, casts shadows) ----
uniform vec3 uSunDir;         // direction TOWARDS the sun
uniform vec3 uSunColor;
// ---- Lights 2..5: point lights. [0] = explorer's lantern, [1..] = ruins glowing while they form / crumble ----
const int MAX_POINTS = 4;
uniform int uNumPoints;
uniform vec3 uPointPos[MAX_POINTS];
uniform vec3 uPointColor[MAX_POINTS];
// ---- Light 6: spotlight = golden light leaking through a crack in the glass dome, aimed at the camel ----
uniform vec3 uSpotPos;
uniform vec3 uSpotDir;        // cone axis (unit vector, from the light downwards)
uniform vec3 uSpotColor;
uniform float uSpotInner, uSpotOuter;   // cos of the inner / outer cone angles (smooth edge in between)
// On/off toggles (F1..F8)
uniform bool uUseSun, uUsePoint, uUseSpot, uUseSpec;

// ---- Shadow mapping (sun only) ----
uniform sampler2D uShadowMap;   // depth of the closest surface, seen from the sun
uniform mat4 uLightSpace;       // world -> sun's clip space (orthographic)
uniform bool uUseShadow;
uniform bool uShadowPass;       // true while rendering the shadow map itself (depth only)

// [Advanced: shadow mapping] 1 = lit by the sun, 0 = in shadow. 3x3 PCF: average 9 depth tests so the
// shadow edge is soft.
float sunShadow(vec3 P, vec3 n) {
    if (!uUseShadow) return 1.0;
    vec4 L = uLightSpace * vec4(P, 1.0);
    vec3 c = L.xyz / L.w * 0.5 + 0.5;                  // NDC [-1,1] -> texture coords + depth in [0,1]
    if (any(lessThan(c, vec3(0.0))) || any(greaterThan(c, vec3(1.0)))) return 1.0;   // outside the shadow box
    // Bias against "shadow acne" (a surface shadowing itself); larger on slopes facing away from the sun
    float bias = max(0.0012 * (1.0 - dot(n, normalize(uSunDir))), 0.0003);
    vec2 texel = 1.0 / vec2(textureSize(uShadowMap, 0));
    float lit = 0.0;
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x)
            lit += (c.z - bias > texture(uShadowMap, c.xy + vec2(x, y) * texel).r) ? 0.0 : 1.0;
    return lit / 9.0;
}

// [Lighting: Blinn-Phong] Adds one light's diffuse and specular contributions
void blinnPhong(vec3 n, vec3 v, vec3 l, vec3 lightColor, float ks, float shininess, inout vec3 diff, inout vec3 spec) {
    float d = max(dot(n, l), 0.0);                              // Lambert: cos of the angle to the light
    vec3 h = normalize(l + v);                                  // half vector between light and viewer
    float s = (uUseSpec && d > 0.0) ? pow(max(dot(n, h), 0.0), shininess) * ks : 0.0;
    diff += lightColor * d;
    spec += lightColor * s;
}

// [Lighting: light sources (directional, point, spot)] Sum of all lights at point P with normal n
void lightAt(vec3 P, vec3 n, float ks, float shininess, out vec3 diff, out vec3 spec) {
    diff = vec3(0.0); spec = vec3(0.0);
    vec3 v = normalize(uCamPos - P);
    if (uUseSun)
        blinnPhong(n, v, normalize(uSunDir), uSunColor * sunShadow(P, n), ks, shininess, diff, spec);
    if (uUsePoint)
        for (int i = 0; i < uNumPoints; ++i) {
            vec3 toL = uPointPos[i] - P;
            float dist = length(toL);
            float att = 1.0 / (1.0 + 0.09 * dist + 0.032 * dist * dist);   // constant + linear + quadratic falloff
            blinnPhong(n, v, toL / dist, uPointColor[i] * att, ks, shininess, diff, spec);
        }
    if (uUseSpot) {
        vec3 toL = uSpotPos - P;
        vec3 l = normalize(toL);
        float cosAngle = dot(-l, uSpotDir);                       // angle between the cone axis and this point
        float cone = clamp((cosAngle - uSpotOuter) / (uSpotInner - uSpotOuter), 0.0, 1.0);
        blinnPhong(n, v, l, uSpotColor * cone, ks, shininess, diff, spec);
    }
}

// The liquid sand is glossy (wet sun glint); models use their own material
float specOf()  { return uMode == MODE_SAND ? 0.35 : uSpec; }
float shineOf() { return uMode == MODE_SAND ? 60.0 : uShininess; }

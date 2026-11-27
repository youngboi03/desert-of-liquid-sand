#pragma once
// Procedural meshes: sphere (sky dome, lantern flame) and the flat grid for the sand.
#include "model.h"
#include <cmath>

static const float PI = 3.14159265f;

inline Mesh withMaterial(Mesh m, glm::vec3 rgb, float spec = 0.1f, float shin = 16.0f,
                         glm::vec3 emissive = glm::vec3(0.0f)) {
    m.color = glm::vec4(rgb, 1.0f);
    m.spec = spec; m.shininess = shin; m.emissive = emissive;
    return m;
}

// Sphere of radius r; sy scales the Y axis (ellipsoid)
inline Mesh makeSphere(float r, glm::vec3 center, glm::vec3 rgb, float sy = 1.0f, int st = 16, int sl = 24) {
    std::vector<Vertex> v; std::vector<unsigned> i;
    for (int a = 0; a <= st; ++a)
        for (int b = 0; b <= sl; ++b) {
            float th = PI * a / st, ph = 2 * PI * b / sl;
            glm::vec3 n(std::sin(th) * std::cos(ph), std::cos(th), std::sin(th) * std::sin(ph));
            v.push_back({center + r * glm::vec3(n.x, n.y * sy, n.z), n, {(float)b / sl, (float)a / st}});
        }
    for (int a = 0; a < st; ++a)
        for (int b = 0; b < sl; ++b) {
            unsigned p = a * (sl + 1) + b, q = p + sl + 1;
            for (unsigned k : {p, q, p + 1, p + 1, q, q + 1}) i.push_back(k);
        }
    return withMaterial(uploadMesh(v, i), rgb);
}

// Flat grid for the liquid sand; the vertex shader lifts every vertex to the sand height each frame
inline Mesh makeGrid(float half, int n) {
    std::vector<Vertex> v; std::vector<unsigned> i;
    float step = 2 * half / n;
    for (int a = 0; a <= n; ++a)
        for (int b = 0; b <= n; ++b)
            v.push_back({{-half + b * step, 0.0f, -half + a * step}, {0, 1, 0}, {0, 0}});
    for (int a = 0; a < n; ++a)
        for (int b = 0; b < n; ++b) {
            unsigned p = a * (n + 1) + b, q = p + n + 1;
            for (unsigned k : {p, q, p + 1, p + 1, q, q + 1}) i.push_back(k);
        }
    return uploadMesh(v, i);
}

#pragma once
// [Advanced: liquid sand] CPU copy of the sand height. MUST match dunes() + waves() in shaders/scene.vert: the camel and the
// ruins are placed on it every frame. (Footstep ripples are only in the shader; they are a few cm.)
#include <cmath>
#include <glm/glm.hpp>

// The camel's trail: an endless winding line, z = 8 sin(x / 25)
inline float trailZ(float x) { return 8.0f * std::sin(x / 25.0f); }
inline float trailSlope(float x) { return 8.0f / 25.0f * std::cos(x / 25.0f); }   // dz/dx, gives the heading

inline float sandDunes(float x, float z) {
    auto smooth = [](float a, float b, float v) { float t = glm::clamp((v - a) / (b - a), 0.0f, 1.0f); return t * t * (3 - 2 * t); };
    float corridor = smooth(4.0f, 16.0f, std::abs(z - trailZ(x)));   // flat lane along the trail
    float qx = x + 6.0f * std::sin(z * 0.031f), qz = z + 6.0f * std::sin(x * 0.027f);
    float d = 2.2f * (1.0f - std::abs(std::sin(qx * 0.045f + qz * 0.020f))) +
              1.3f * (1.0f - std::abs(std::sin(qz * 0.060f - qx * 0.025f)));
    return corridor * d * 1.6f;
}

inline float sandWaves(float x, float z, float t) {
    return 0.45f * std::sin(0.10f * x + 0.06f * z - 0.6f * t) +          // long, slow swell
           0.30f * std::sin(0.28f * x + 0.10f * z - 1.1f * t) +
           0.18f * std::sin(-0.12f * x + 0.31f * z - 0.8f * t + 1.3f) +
           0.07f * std::sin(0.60f * x + 0.50f * z - 1.9f * t);
}

inline float sandHeight(float x, float z, float t) { return sandDunes(x, z) + sandWaves(x, z, t); }

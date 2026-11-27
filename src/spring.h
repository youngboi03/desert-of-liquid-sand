#pragma once
// [Advanced: secondary motion (springs)] Two small physics helpers that make motion look natural
// instead of a fixed sine wave.
#include <glm/glm.hpp>
#include <cmath>

// A damped spring (Hooke's law + damping, mass = 1):
//     acceleration = stiffness * (target - x) - damping * velocity + force
// x follows its target with inertia: it lags behind, overshoots a little and settles.
// `force` is an extra push, e.g. the inertia felt when the thing it sits on accelerates.
// Integrated with semi-implicit Euler (update the velocity first, then the position), in small sub-steps
// so a long frame cannot make it explode.
struct Spring {
    float stiffness, damping;
    float x = 0.0f, v = 0.0f;

    Spring(float k = 40.0f, float c = 8.0f) : stiffness(k), damping(c) {}

    float update(float target, float dt, float force = 0.0f) {
        int steps = (int)std::ceil(dt / (1.0f / 120.0f));
        float h = steps > 0 ? dt / steps : 0.0f;
        for (int i = 0; i < steps; ++i) {
            float a = stiffness * (target - x) - damping * v + force;
            v += a * h;
            x += v * h;
        }
        return x;
    }
};

// Velocity and acceleration of a moving point, from its positions in consecutive frames
// (finite differences: v = dp / dt, a = dv / dt).
struct MotionTracker {
    glm::vec3 lastPos{0.0f}, lastVel{0.0f};
    glm::vec3 vel{0.0f}, acc{0.0f};
    int frames = 0;   // needs 3 frames before the acceleration is meaningful

    void update(const glm::vec3& p, float dt) {
        if (dt <= 0.0f) return;
        vel = frames >= 1 ? (p - lastPos) / dt : glm::vec3(0.0f);
        acc = frames >= 2 ? (vel - lastVel) / dt : glm::vec3(0.0f);
        acc = glm::clamp(acc, glm::vec3(-30.0f), glm::vec3(30.0f));   // ignore spikes (e.g. a camera cut)
        lastPos = p; lastVel = vel; ++frames;
    }
};

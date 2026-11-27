#pragma once
// User-controlled camera: 3 camel-following modes, free roam, and a rider view on the explorer's head.
#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <cmath>

enum class CamMode { Follow = 1, Side = 2, Overview = 3, Free = 4, Rider = 5 };

struct Camera {
    CamMode mode = CamMode::Follow;
    glm::vec3 pos{0.0f, 6.0f, 20.0f};
    glm::vec3 lookAt{0.0f};
    float userYaw = 0.0f, pitch = 0.35f, dist = 9.0f;   // orbit around the target (mouse / scroll)
    float fov = 50.0f;
    // Free mode
    float freeYaw = 0.0f, freePitch = 0.0f;

    // Mouse drag: orbit the camel (first 3 modes) or look around (Free)
    void drag(float dx, float dy) {
        if (mode == CamMode::Free) {
            freeYaw += dx * 0.004f;
            freePitch = glm::clamp(freePitch - dy * 0.004f, -1.5f, 1.5f);
        } else {
            userYaw -= dx * 0.005f;
            pitch = glm::clamp(pitch + dy * 0.005f, 0.05f, 1.4f);
        }
    }
    float speed = 8.0f;                                     // free-roam walking speed (m/s)
    void scroll(float s) {                                  // zoom the orbit, or change the walking speed
        if (mode == CamMode::Free) speed = glm::clamp(speed * (s > 0 ? 1.25f : 0.8f), 2.0f, 60.0f);
        else dist = glm::clamp(dist - s * 0.8f, 3.0f, 40.0f);
    }

    void setMode(CamMode m) {
        if (m == mode) return;
        if (m == CamMode::Free) {   // continue flying from the current pose, no visual jump
            glm::vec3 d = glm::normalize(lookAt - pos);
            freeYaw = std::atan2(d.z, d.x);
            freePitch = std::asin(d.y);
        }
        if (m == CamMode::Rider) { userYaw = 0.0f; pitch = 0.35f; }   // start looking straight ahead
        mode = m;
    }

    // target/heading: camel position and travel angle (atan2(dz, dx)) in the XZ plane
    void update(GLFWwindow* w, float dt, const glm::vec3& target, float heading) {
        if (mode == CamMode::Free) {
            glm::vec3 fwd(std::cos(freePitch) * std::cos(freeYaw), std::sin(freePitch),
                          std::cos(freePitch) * std::sin(freeYaw));
            glm::vec3 right = glm::normalize(glm::cross(fwd, glm::vec3(0, 1, 0)));
            float v = (glfwGetKey(w, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS ? 3.0f : 1.0f) * speed * dt;   // Shift = run
            auto key = [&](int k) { return glfwGetKey(w, k) == GLFW_PRESS; };
            if (key(GLFW_KEY_W)) pos += fwd * v;
            if (key(GLFW_KEY_S)) pos -= fwd * v;
            if (key(GLFW_KEY_D)) pos += right * v;
            if (key(GLFW_KEY_A)) pos -= right * v;
            if (key(GLFW_KEY_E)) pos.y += v;
            if (key(GLFW_KEY_Q)) pos.y -= v;
            lookAt = pos + fwd;
            return;
        }
        glm::vec3 desired, aim = target;
        if (mode == CamMode::Overview) {            // overview: high orbit around the camel and its surroundings
            float a = userYaw + 0.6f;
            desired = target + glm::vec3(std::cos(a), 0.0f, std::sin(a)) * (dist * 2.5f);
            desired.y = target.y + 4.0f + dist * 1.5f * std::sin(pitch);
        } else {
            // Follow: behind the camel (heading + 180 deg). Side: extra 90 deg to view its flank.
            float a = heading + glm::pi<float>() + userYaw + (mode == CamMode::Side ? glm::half_pi<float>() : 0.0f);
            desired = target + dist * glm::vec3(std::cos(pitch) * std::cos(a), std::sin(pitch), std::cos(pitch) * std::sin(a));
        }
        pos = glm::mix(pos, desired, 1.0f - std::exp(-5.0f * dt));   // smooth follow (slight lag)
        lookAt = glm::mix(lookAt, aim, 1.0f - std::exp(-8.0f * dt));
    }

    // Rider view: the camera is attached to the explorer's head node, so it inherits the whole chain
    // camel -> body -> explorer -> torso -> head (it sways with the camel and turns as the head looks around).
    // Mouse drag still looks around relative to the head.
    void attach(const glm::mat4& head) {
        glm::vec3 eye(0.0f, 0.14f, 0.22f);                       // just in front of the face (head frame faces +Z)
        glm::vec3 dir(std::sin(userYaw), 0.35f - pitch - 0.45f, std::cos(userYaw));   // looks a little down
        pos = glm::vec3(head * glm::vec4(eye, 1.0f));
        lookAt = pos + glm::normalize(glm::vec3(head * glm::vec4(dir, 0.0f)));
    }

    glm::mat4 view() const { return glm::lookAt(pos, lookAt, glm::vec3(0, 1, 0)); }
};

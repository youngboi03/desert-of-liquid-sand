#pragma once
// [Advanced: shadow mapping] Shadows from the sun (directional light).
//
// Pass 1: render the scene from the sun with an orthographic camera into a depth-only texture.
//         Each texel stores the distance to the closest surface the sun "sees".
// Pass 2: normal render. For each pixel, transform its world position into the sun's space and compare
//         its depth with the stored one: if something closer to the sun is stored, the pixel is in shadow
//         (see sunShadow() in shaders/common.glsl).
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

struct ShadowMap {
    static const int SIZE = 4096;     // texels per side
    GLuint fbo = 0, depthTex = 0;

    void init() {
        glGenTextures(1, &depthTex);
        glBindTexture(GL_TEXTURE_2D, depthTex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, SIZE, SIZE, 0, GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        // Outside the map = depth 1 (farthest) = never in shadow
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
        float border[4] = {1.0f, 1.0f, 1.0f, 1.0f};
        glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, border);

        glGenFramebuffers(1, &fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depthTex, 0);
        glDrawBuffer(GL_NONE);        // no colour output
        glReadBuffer(GL_NONE);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    // The sun's camera: looks along -sunDir at the camel (the box moves with the journey). The box is wide (x)
    // and short (y) because the low sun stretches everything along its direction.
    static glm::mat4 lightView(const glm::vec3& sunDir, const glm::vec3& camelPos) {
        glm::vec3 centre(camelPos.x, 2.0f, camelPos.z);
        return glm::lookAt(centre + sunDir * 100.0f, centre, glm::vec3(0, 1, 0));
    }
    static glm::mat4 lightProj() { return glm::ortho(-42.0f, 42.0f, -20.0f, 20.0f, 40.0f, 170.0f); }

    void begin() {
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glViewport(0, 0, SIZE, SIZE);
        glClear(GL_DEPTH_BUFFER_BIT);
        glEnable(GL_POLYGON_OFFSET_FILL);   // push depths back a little: less self-shadowing (acne)
        glPolygonOffset(2.0f, 4.0f);
    }
    void end(int screenW, int screenH) {
        glDisable(GL_POLYGON_OFFSET_FILL);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, screenW, screenH);
    }
};

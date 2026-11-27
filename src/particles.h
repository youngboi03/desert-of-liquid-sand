#pragma once
// [Advanced: transparent particles] Sand dust drawn as point sprites with alpha blending.
// Emitted by ruins while they form / crumble (ruins.h) and by the camel's footsteps (main.cpp).
//
// Each frame: move every particle (wind, weak gravity, drag), delete the dead ones, sort the rest from far
// to near, upload them to one VBO and draw GL_POINTS.
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <algorithm>
#include <cstdlib>
#include <vector>

inline float rnd(float a, float b) { return a + (b - a) * (float)std::rand() / (float)RAND_MAX; }

struct Particle {
    glm::vec3 pos, vel;
    glm::vec3 color;
    float size;          // diameter in metres
    float age, life;     // seconds
};

struct Dust {
    static const int MAX = 4000;
    std::vector<Particle> ps;
    GLuint vao = 0, vbo = 0;

    void init() {
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, MAX * 8 * sizeof(float), nullptr, GL_STREAM_DRAW);
        glEnableVertexAttribArray(0);   // xyz = position, w = size
        glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, 8 * sizeof(float), (void*)0);
        glEnableVertexAttribArray(1);   // rgb = colour, a = opacity
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, 8 * sizeof(float), (void*)(4 * sizeof(float)));
        glBindVertexArray(0);
    }

    void emit(const glm::vec3& pos, const glm::vec3& vel, const glm::vec3& color, float size, float life) {
        if ((int)ps.size() < MAX) ps.push_back({pos, vel, color, size, 0.0f, life});
    }

    void update(float dt) {
        for (Particle& p : ps) {
            p.vel += glm::vec3(0.35f, -0.25f, 0.15f) * dt;   // light wind + weak gravity: dust hangs in the air
            p.vel *= 1.0f - 0.6f * dt;                       // air drag
            p.pos += p.vel * dt;
            p.age += dt;
        }
        ps.erase(std::remove_if(ps.begin(), ps.end(), [](const Particle& p) { return p.age >= p.life; }), ps.end());
    }

    void draw(GLuint program, const glm::mat4& view, const glm::mat4& proj, const glm::vec3& camPos, int screenH) {
        if (ps.empty()) return;
        // Back to front: a far particle must be blended before a near one covers it
        std::sort(ps.begin(), ps.end(), [&](const Particle& a, const Particle& b) {
            return glm::length(a.pos - camPos) > glm::length(b.pos - camPos);
        });
        std::vector<float> data;
        data.reserve(ps.size() * 8);
        for (const Particle& p : ps) {
            float t = p.age / p.life;
            float alpha = std::min(t * 6.0f, 1.0f) * (1.0f - t);     // quick fade in, slow fade out
            float d[8] = {p.pos.x, p.pos.y, p.pos.z, p.size, p.color.r, p.color.g, p.color.b, alpha};
            data.insert(data.end(), d, d + 8);
        }
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferSubData(GL_ARRAY_BUFFER, 0, data.size() * sizeof(float), data.data());

        glUseProgram(program);
        glUniformMatrix4fv(glGetUniformLocation(program, "uView"), 1, GL_FALSE, &view[0][0]);
        glUniformMatrix4fv(glGetUniformLocation(program, "uProj"), 1, GL_FALSE, &proj[0][0]);
        glUniform1f(glGetUniformLocation(program, "uScreenH"), (float)screenH);

        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);   // result = src * a + dst * (1 - a)
        glDepthMask(GL_FALSE);                               // test against the scene but do not hide each other
        glEnable(GL_PROGRAM_POINT_SIZE);                     // the vertex shader sets gl_PointSize
        glBindVertexArray(vao);
        glDrawArrays(GL_POINTS, 0, (GLsizei)ps.size());
        glBindVertexArray(0);
        glDisable(GL_PROGRAM_POINT_SIZE);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
    }
};

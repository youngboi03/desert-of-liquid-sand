#pragma once
// Ruins that exist only along the journey: they form out of sand dust ahead of the camel and crumble behind it.
//
// The ruins are laid out in a repeating pattern along the trail (world.h buildRuins). Each one has an offset
// in that pattern and a sideways distance from the trail. While it is invisible it moves one pattern length
// further ahead, so the journey never runs out of ruins. Some of them float in the air.
// `presence` (0 = gone, 1 = solid) moves smoothly towards its target and drives:
//   - the dissolve threshold in the fragment shader (uDissolve = 1 - presence),
//   - an orange point light at the ruin while it glows (main.cpp picks the brightest ones),
//   - dust particles emitted around it.
#include "node.h"
#include "geometry.h"
#include "particles.h"
#include "sand.h"
#include <cmath>

struct Ruin {
    Node* node = nullptr;
    const Model* model = nullptr;
    float pattern = 90.0f;     // the layout repeats every `pattern` metres of trail
    float offset = 0.0f;       // position inside the repeating pattern (m along the trail)
    float side = 0.0f;         // sideways distance from the trail (m, positive = left); 0 = on the trail
    float yaw = 0.0f, scale = 1.0f;
    bool alongTrail = false;   // turn the model's X axis along the trail (gateways, avenues, fallen columns);
                               // `yaw` is then added on top (e.g. PI turns a cliff face towards the trail)
    float trailYaw = 0.0f;     // direction of the trail where it stands (set in place())
    bool backdrop = false;     // far landmark (cliffs, mesas, trees): no glow light, no dust
    float tilt = 0.0f;         // fixed lean (rad) about the model's Z axis: a leaning or fallen piece
    float sink = 0.0f;         // metres buried in the sand (half-buried statues)
    float floatHeight = 0.0f;  // > 0: an impossible floating ruin, this high above the dunes
    bool drift = true;         // floating: spin and tumble slowly (false = hang still, keeping its yaw)
    glm::vec3 pos{0.0f};       // where it currently stands (fixed while it is visible)
    float presence = 0.0f, lastPresence = 0.0f;

    // View window: near pieces appear 60 m ahead and go 12 m behind the camel; far landmarks (large |side|)
    // appear earlier and stay longer so the horizon is never empty. Capped so the window fits in the pattern.
    float reach() const  { return std::min(60.0f + 1.2f * std::abs(side), 0.65f * pattern); }
    float behind() const { return std::min(12.0f + 0.5f * std::abs(side), 0.25f * pattern); }

    // [Advanced: endless journey (ruin recycling)] Distance ahead of the camel, wrapped into
    // [-behind-8, pattern-behind-8): once passed and crumbled, the ruin comes back one pattern further ahead
    float ahead(float camelX) const {
        float lo = -behind() - 8.0f;
        float d = std::fmod(offset - camelX - lo, pattern);
        if (d < 0.0f) d += pattern;
        return d + lo;
    }

    float target(float camelX) const {
        float a = ahead(camelX);
        return (a > -behind() && a < reach()) ? 1.0f : 0.0f;
    }

    // Brightness of the glowing edge: strongest half-way through forming / crumbling
    float glow() const { return backdrop ? 0.0f : 4.0f * presence * (1.0f - presence); }

    // Move it to its next spot along the trail (only while invisible, so nothing pops)
    void place(float camelX) {
        float x = camelX + ahead(camelX);
        glm::vec3 dir = glm::normalize(glm::vec3(1.0f, 0.0f, trailSlope(x)));   // trail direction there
        glm::vec3 normal(dir.z, 0.0f, -dir.x);                                    // to the traveller's left
        pos = glm::vec3(x, 0.0f, trailZ(x)) + normal * side;
        if (alongTrail) trailYaw = std::atan2(-dir.z, dir.x);   // rotates the model's +X onto `dir`
    }

    void update(float dt, float camelX, float time, Dust& dust) {
        lastPresence = presence;
        float goal = target(camelX);
        float rate = goal > presence ? 0.30f : 0.40f;              // ~3.3 s to form, 2.5 s to crumble
        presence += glm::clamp(goal - presence, -rate * dt, rate * dt);
        if (presence <= 0.0f) place(camelX);

        glm::vec3 p = pos;
        glm::mat4 tilt(1.0f);
        float spin = 0.0f;
        if (floatHeight > 0.0f) {                                    // floating: bob, lean and spin slowly
            p.y = sandDunes(p.x, p.z) + floatHeight + 0.4f * std::sin(0.8f * time + offset);
            float sway = drift ? 0.3f : 0.03f;                       // a "still" piece only breathes
            tilt = glm::rotate(glm::mat4(1.0f), sway * std::sin(0.25f * time + side), glm::vec3(1, 0, 0));
            spin = drift ? 0.2f * time : 0.0f;
        } else {                                                     // standing: rises out of the liquid sand
            float rise = 1.8f * (1.0f - presence) * (1.0f - presence);
            p.y = sandHeight(p.x, p.z, time) - 0.6f - sink - rise;
        }
        node->base = glm::translate(glm::mat4(1.0f), p) * tilt *
                     glm::rotate(glm::mat4(1.0f), trailYaw + yaw + spin, glm::vec3(0, 1, 0)) *
                     glm::rotate(glm::mat4(1.0f), this->tilt, glm::vec3(0, 0, 1)) *
                     glm::scale(glm::mat4(1.0f), glm::vec3(scale));

        // Dust: random points inside the model's bounding box, drifting up and away
        if (!backdrop && presence > 0.0f && presence < 1.0f && dt > 0.0f) {
            bool forming = presence > lastPresence;
            int count = (int)(140.0f * dt * scale + rnd(0.0f, 1.0f));
            for (int i = 0; i < count; ++i) {
                glm::vec3 local(rnd(model->minB.x, model->maxB.x), rnd(model->minB.y, model->maxB.y),
                                rnd(model->minB.z, model->maxB.z));
                glm::vec3 q = glm::vec3(node->world * glm::vec4(local, 1.0f));
                glm::vec3 v(rnd(-0.4f, 0.4f), rnd(0.3f, 1.2f), rnd(-0.4f, 0.4f));
                glm::vec3 c = forming ? glm::vec3(1.0f, 0.78f, 0.45f) : glm::vec3(1.0f, 0.55f, 0.25f);   // forming: golden, crumbling: ember
                dust.emit(q, v, c, rnd(0.05f, 0.14f), rnd(1.5f, 3.5f));
            }
        }
    }
};

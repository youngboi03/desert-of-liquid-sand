#pragma once
// world.h - WHAT is in the scene and HOW it moves:
//   building  : load the .glb models and put them in the scene graph (camel + rider rig, lantern, rocks, ruins)
//   update()  : one simulation step = walk the camel along the trail, animate camel and rider, move the ruins,
//               swing the lantern, start footstep ripples and dust.
// Nothing in this file draws: rendering is in main.cpp.
#include <algorithm>
#include <cmath>
#include <deque>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include "model.h"
#include "geometry.h"
#include "node.h"
#include "sand.h"
#include "particles.h"
#include "ruins.h"
#include "spring.h"

static const glm::vec3 LAMP_CORE(0.0f, -0.17f, 0.0f);      // flame inside the lantern, below its top ring
static const float LEG_PHASE[4] = {0.0f, PI, 0.5f, PI + 0.5f};   // FL, FR, RL, RR: pace gait, hind legs lag slightly
static const float WALK_SPEED = 2.4f;                      // m/s
static const float STRIDE = 2.4f;                          // m per gait cycle
static const int MAX_RIPPLES = 24;                         // must match scene.vert / scene.frag

// Riding posture: offsets (rad) from the explorer model's rest pose
static const float POSE_ARM = 0.85f, POSE_ELBOW = -0.5f, POSE_THIGH = 0.35f, POSE_KNEE = -0.2f;

struct World {
    // ---------------- storage (deques: pointers stay valid when more items are added) ----------------
    std::deque<Model> models;
    std::deque<Mesh> meshes;
    std::deque<Node> nodes;
    std::deque<Skin> skins;

    // ---------------- the scene graph ----------------
    // Camel skeleton (blender/camel.blend). Legs: [front-left, front-right, back-left, back-right] x [thigh, shin, foot]
    Node *camelRoot, *camelModel, *spine, *neck1, *neck2, *head, *tail, *leg[4][3];
    // Explorer skeleton (blender/explorer.blend), seated pose = rest pose. Index 0 = left, 1 = right.
    Node *explorer, *hips, *spineE, *chest, *headE, *shoulder[2], *upperArm[2], *forearm[2], *hand[2],
         *thigh[2], *shin[2], *foot[2], *cloak[3];
    Node* lantern;                                    // hangs from the left hand (pendulum)
    static const int NROCKS = 9;
    const float ROCK_HEIGHT[NROCKS] = {8.0f, 10.5f, 7.0f, 12.0f, 9.0f, 15.0f, 8.5f, 13.5f, 18.0f};
    Node *rockRing, *rocks[NROCKS];                   // a ring of rocks orbiting the traveller
    const Model* boulderModel = nullptr;
    std::vector<Ruin> ruins;                          // appear / crumble along the journey (ruins.h)
    glm::mat4 explorerSeat{1.0f};

    // ---------------- simulation state ----------------
    float simTime = 0.0f;           // seconds of simulation
    float camelX = -45.0f;          // how far along the trail (the trail is z = trailZ(x)); starts before the city gate
    float phi = 0.0f;               // gait phase (rad): one stride = 2 pi
    glm::vec3 camelPos{0.0f}, camelDir{1.0f, 0.0f, 0.0f};
    float heading = 0.0f;           // travel angle in XZ, atan2(dir.z, dir.x) (for the cameras)
    float slopePitch = 0.0f;        // the camel's nose-up tilt on the sand (rad)
    glm::vec4 ripples[MAX_RIPPLES] = {};   // footstep ripples: (x, z, start time, strength), ring buffer
    int nextRipple = 0;
    bool legInAir[4] = {};
    Dust dust;

    // Rider physics: the torso balances on the pelvis like an inverted pendulum held by a spring (muscles)
    MotionTracker saddle;
    Spring torsoPitch{55.0f, 9.0f}, torsoRoll{55.0f, 9.0f};
    Spring chestPitch{120.0f, 14.0f}, chestRoll{120.0f, 14.0f};   // the chest follows a little later
    Spring lookYaw{10.0f, 6.3f}, lookPitch{10.0f, 6.3f};          // head turns smoothly to a new target
    Spring cloakPitch{110.0f, 6.5f}, cloakRoll{110.0f, 6.5f};     // cloth: ~1.7 Hz, bouncy (under-damped)
    float lookTimer = 0.0f, lookYawTarget = 0.0f, lookPitchTarget = 0.0f;
    // Lantern pendulum
    MotionTracker handTracker;
    glm::vec2 swing{0.0f}, swingVel{0.0f};

    // =====================================================================================================
    // Building
    // =====================================================================================================
    void build() {
        buildCamel();
        buildExplorer();
        buildRocks();
        buildRuins();
        buildBackdrop();
        update(0.0f);                                // place everything once
        for (Ruin& r : ruins) {                       // start with the ruins around the camel already standing
            r.place(camelX);
            r.presence = r.target(camelX);
        }
    }

    Node* node() { nodes.emplace_back(); return &nodes.back(); }
    Mesh* mesh(Mesh m) { meshes.push_back(std::move(m)); return &meshes.back(); }

    Model& load(const std::string& file, bool hierarchy) {
        models.emplace_back();
        if (!models.back().load(std::string(ASSET_DIR) + "models/" + file, hierarchy)) {
            std::cerr << file << " load failed" << std::endl;
            std::exit(1);
        }
        return models.back();
    }

    // Static prop: Blender already put the origin where the code needs it (blender/props.blend)
    Node* propNode(const Model& m) {
        Node* n = node();
        for (const Mesh& me : m.meshes) n->meshes.push_back(&me);
        return n;
    }

    // [Advanced: skinning + scene graph] Each .glb skeleton becomes a tree of Nodes (node.h); a bone's
    // angle moves all its children, and update() walks the tree parent -> child.
    void buildCamel() {
        Model& m = load("camel.glb", true);
        camelRoot = node();                                  // camel position + heading + slope on the sand
        Node* rig = camelRoot->add(node());                  // centre the body over the origin, feet on y = 0
        rig->base = glm::translate(glm::mat4(1.0f), glm::vec3(-0.4f, 0.017f, 0.0f));
        camelModel = rig->add(buildNodeTree(m, nodes, skins, camelBones));
        spine = camelBones.at("Spine");
        neck1 = camelBones.at("Neck1"); neck2 = camelBones.at("Neck2"); head = camelBones.at("Head");
        tail = camelBones.at("Tail");
        const char* legName[4] = {"F.L", "F.R", "B.L", "B.R"};
        const char* part[3] = {"Thigh.", "Shin.", "Foot."};
        for (int l = 0; l < 4; ++l)
            for (int p = 0; p < 3; ++p) leg[l][p] = camelBones.at(std::string(part[p]) + legName[l]);
    }

    // The explorer is parented to the camel's Spine bone, so he rides along with every step
    void buildExplorer() {
        Model& m = load("explorer.glb", true);
        explorer = spine->add(node());
        explorer->add(buildNodeTree(m, nodes, skins, explorerBones));
        // Seat measured in explorer.blend against a reference camel: hips on the saddle, facing the
        // camel's +X. It is given in the camel's model frame, so convert it into the Spine bone's frame.
        camelRoot->update(glm::mat4(1.0f));
        glm::mat4 seat = glm::translate(glm::mat4(1.0f), glm::vec3(0.1f, 1.3f, 0.0f)) *
                         glm::rotate(glm::mat4(1.0f), glm::half_pi<float>(), glm::vec3(0, 1, 0));
        explorerSeat = glm::inverse(spine->world) * camelModel->world * seat;
        explorer->base = explorerSeat;
        auto bone = [&](const std::string& n) { return explorerBones.at(n); };
        hips = bone("Hips"); spineE = bone("Spine"); chest = bone("Chest"); headE = bone("Head");
        const char* s[2] = {"L", "R"};
        for (int i = 0; i < 2; ++i) {
            std::string sfx = std::string(".") + s[i];
            shoulder[i] = bone("Shoulder" + sfx); upperArm[i] = bone("UpperArm" + sfx);
            forearm[i] = bone("Forearm" + sfx); hand[i] = bone("Hand" + sfx);
            thigh[i] = bone("Thigh" + sfx); shin[i] = bone("Shin" + sfx); foot[i] = bone("Foot" + sfx);
        }
        cloak[0] = bone("Cloak.Back"); cloak[1] = bone("Cloak.L"); cloak[2] = bone("Cloak.R");
        // Lantern (Poly Haven scan, origin at its top ring) + a glowing core that is also the point light
        lantern = propNode(load("lantern.glb", false));
        lantern->meshes.push_back(mesh(withMaterial(makeSphere(0.035f, LAMP_CORE, glm::vec3(1.0f)),
                                                    glm::vec3(0.55f, 0.85f, 1.0f), 0.0f, 1.0f, glm::vec3(0.5f, 0.85f, 1.0f))));
    }

    void buildRocks() {
        rockRing = node();
        float radius[NROCKS] = {15.0f, 18.0f, 21.0f, 24.0f, 27.0f, 30.0f, 16.0f, 22.0f, 34.0f};
        float size[NROCKS] = {1.2f, 2.0f, 0.8f, 1.6f, 1.9f, 2.6f, 0.6f, 1.1f, 3.2f};   // boulder.glb is 1.9 m tall
        boulderModel = &load("boulder.glb", false);
        const Model& boulder = *boulderModel;
        for (int k = 0; k < NROCKS; ++k) {
            float a = k * 2.0f * PI / NROCKS + 0.3f * (k % 2);
            rocks[k] = rockRing->add(propNode(boulder));
            rocks[k]->base = glm::translate(glm::mat4(1.0f), glm::vec3(radius[k] * std::cos(a), ROCK_HEIGHT[k], radius[k] * std::sin(a))) *
                             glm::scale(glm::mat4(1.0f), glm::vec3(size[k]));
        }
    }

    // The layout of one stretch of the lost city along the trail (it repeats, see ruins.h). Models: Sketchfab
    // (CC-BY, assets/source/sketchfab_dl/license.txt) and Poly Haven (CC0), cleaned in blender/scripts/build_sf_*.py
    // and build_props2.py. A walk-through piece (gate, pylon, pavilion) is put where the trail runs straight.
    void buildRuins() {
        const float C = 50.0f * PI;   // 157 m = one full wave of the trail z = 8 sin(x/25): straight at 0 and C/2
        auto tinted = [&](const char* file, glm::vec3 tint) -> const Model& {
            Model& m = load(file, false);
            for (Mesh& me : m.meshes) me.color = glm::vec4(tint, 1.0f);
            return m;
        };
        const Model& pylon    = load("sf_edfu_pylon.glb", false);      // walk-through along X
        const Model& temple   = load("sf_edfu_temple.glb", false);     // carved front = +X
        const Model& pavilion = load("sf_egyptian_ruins.glb", false);  // walk-through along X
        Model& colossus = load("sf_colossus.glb", false);              // face = +Z
        for (Mesh& me : colossus.meshes) { me.spec = 0.6f; me.shininess = 40.0f; }   // polished bronze
        const Model& gate     = tinted("sf_sandstone_gate.glb", {1.35f, 1.25f, 1.1f});
        const Model& arch2    = tinted("sf_set_arch.glb", {1.0f, 0.8f, 0.58f});
        const Model& arcade   = tinted("sf_set_arcade.glb", {1.0f, 0.8f, 0.58f});       // long axis = Z
        const Model& fallen   = tinted("sf_set_fallen_tower.glb", {1.0f, 0.8f, 0.58f});
        const Model& tower    = load("sf_dr_tower.glb", false);        // stairs = +X
        const Model& stump    = load("sf_dr_tower_stump.glb", false);
        const Model& wall     = load("sf_dr_wall.glb", false);
        const Model& shrine   = load("sf_dr_shrine.glb", false);       // open arch = +X
        const Model& room     = load("sf_pack_room.glb", false);       // open towards +X/+Z
        const Model& corner   = load("sf_pack_tower.glb", false);
        const Model& steps    = load("sf_pack_wall.glb", false);
        const Model& drums    = load("sf_pack_rubble.glb", false);
        const Model& naturalArch = load("sf_carved_cliff.glb", false);
        const Model& lion     = load("lion_head.glb", false);          // heads face +Z
        const Model& bull     = load("bull_head.glb", false);
        const Model& bust     = load("marble_bust_01.glb", false);
        const Model& cat      = load("concrete_cat_statue.glb", false);
        const Model& vase     = load("antique_ceramic_vase_01.glb", false);
        const Model& arch     = load("arch.glb", false);
        const Model& rubble   = load("ruins.glb", false);
        Model& pillar = load("pillar.glb", false);
        for (Mesh& me : pillar.meshes) me.color = glm::vec4(1.5f, 1.0f, 0.62f, 1.0f);   // teal texture -> sandstone
        const Model& boulder = *boulderModel;                           // loaded in buildRocks()
        const glm::vec3 WARM(1.3f, 1.08f, 0.8f);                       // greyish sandstone -> honey
        // Ruin kit modelled in Blender (blender/scripts/build_ruin_kit.py)
        const Model& column   = tinted("column_intact.glb", WARM);
        const Model& broken   = tinted("column_broken.glb", WARM);
        const Model& lying    = tinted("column_fallen.glb", WARM);
        const Model& drum     = tinted("column_drum.glb", WARM);
        const Model& bay      = tinted("colonnade_bay.glb", WARM);
        const Model& cityWall = load("wall_run.glb", false);
        const Model& podium   = load("temple_podium.glb", false);      // stairs = +Z
        const Model& portico  = load("temple_portico.glb", false);     // face = +Z
        const Model& obelisk  = load("obelisk.glb", false);
        const Model& monolith = load("monolith.glb", false);
        const Model& sarcophagus = load("sarcophagus.glb", false);
        const Model& mastaba  = tinted("mastaba.glb", {2.0f, 1.6f, 1.15f});      // grey texture -> sandstone
        const Model& house    = tinted("house_ruin.glb", {2.3f, 1.9f, 1.5f});    // dark texture -> sandstone

        // yaw is measured from the trail direction: 0 = the model's +X points along the trail
        auto add = [&](const Model& m, float offset, float side, float scale, float yaw, float sink,
                       float floatHeight = 0.0f) {
            Ruin r;
            r.node = propNode(m); r.model = &m;
            r.pattern = C; r.offset = offset; r.side = side; r.scale = scale;
            r.alongTrail = true; r.yaw = yaw; r.sink = sink; r.floatHeight = floatHeight;
            ruins.push_back(r);
        };
        // Turn a model's front towards the trail: front = +Z (statues, heads) or +X (temple, tower, shrine)
        auto faceZ = [](float side) { return side > 0.0f ? 0.0f : PI; };
        auto faceX = [](float side) { return side > 0.0f ? -0.5f * PI : 0.5f * PI; };

        // 1. The city gate: the camel walks through a temple pylon guarded by two colossi and giant heads
        add(pylon, 0.0f, 0.0f, 0.8f, PI, 0.4f);                       // carved front faces the arriving camel
        add(colossus, C - 14.0f,  15.0f, 0.8f, faceZ( 15.0f) - 0.4f, 0.8f);   // turned towards the traveller
        add(colossus, C - 14.0f, -15.0f, 0.8f, faceZ(-15.0f) + 0.4f, 0.8f);
        add(lion, C - 28.0f,  8.0f, 1.4f, faceZ( 8.0f) - 0.3f, 1.0f);
        add(bull, C - 36.0f, -9.0f, 1.4f, faceZ(-9.0f) + 0.3f, 0.8f);

        // 2. The processional avenue: two more gates, arcades on both sides, a colonnade and broken walls
        add(gate, 26.0f, 0.0f, 1.1f, 0.0f, 0.1f);
        add(arch2, 50.0f, 0.0f, 1.5f, 0.0f, 0.1f);
        add(arcade, 38.0f,  9.5f, 1.0f, 0.5f * PI, 0.2f);             // long axis (Z) turned along the trail
        add(arcade, 38.0f, -9.5f, 1.0f, 0.5f * PI, 0.2f);
        // Colonnade: intact columns on the right, broken ones on the left, pillars floating above
        for (int k = 0; k < 5; ++k) {
            add(column, 6.0f + 5.0f * k, -5.5f, 1.0f, 0.3f * k, 0.0f);
            add(broken, 8.0f + 5.0f * k, 6.0f, 1.0f, 1.1f * k, 0.0f);
        }
        add(bay, 58.0f, -6.5f, 1.0f, 0.0f, 0.0f);
        add(lying, 56.0f, 7.0f, 1.0f, 0.2f, 0.1f);
        for (int k = 0; k < 4; ++k)
            add(pillar, 10.0f + 15.0f * k, k % 2 ? 10.0f : -11.0f, 0.6f + 0.1f * k, 0.0f, 0.0f, 3.0f + 0.8f * k);
        // An "exploded" column: its drums hang stacked in the air above their own stump
        add(broken, 64.0f, -10.0f, 1.0f, 0.0f, 0.0f);
        for (int k = 0; k < 3; ++k) {
            add(drum, 64.0f, -10.0f, 1.0f, 0.5f * k, 0.0f, 4.6f + 1.25f * k);
            ruins.back().drift = false;
        }
        // City wall running across the trail on both sides of the pylon
        for (float side : {-27.0f, -35.0f, 27.0f, 35.0f}) add(cityWall, 0.0f, side, 1.0f, 0.5f * PI, 0.3f);
        add(obelisk, 9.0f, 10.0f, 1.0f, 0.0f, 0.0f);
        add(obelisk, 9.0f, -10.0f, 1.0f, 0.0f, 0.0f);                  // the second obelisk leans
        ruins.back().tilt = 0.12f;
        add(wall, 20.0f,  12.0f, 1.1f,  0.0f, 0.2f);
        add(wall, 33.0f, -13.0f, 0.9f,  0.3f, 0.2f);
        add(wall, 62.0f,  14.0f, 1.2f, -0.2f, 0.2f);
        add(corner, 14.0f, -12.0f, 1.2f, 0.8f, 0.0f);
        add(steps, 46.0f, 16.0f, 1.3f, 2.0f, 0.2f);
        add(drums, 22.0f, -8.5f, 1.0f, 1.1f, 0.2f);
        add(shrine, 68.0f, -11.0f, 1.4f, faceX(-11.0f), 0.1f);
        add(bust, 72.0f, 13.0f, 1.5f, faceZ(13.0f) - 0.5f, 2.2f);

        // 3. The temple court (second straight stretch): walk through a columned pavilion, the great temple
        //    stands to the left and a third colossus to the right
        add(pavilion, C / 2, 0.0f, 1.0f, 0.0f, 0.55f);                 // entrance faces the arriving camel
        add(cat, C / 2 - 9.0f,  6.5f, 1.3f, faceZ( 6.5f) - 0.4f, 0.3f);
        add(cat, C / 2 - 9.0f, -6.5f, 1.3f, faceZ(-6.5f) + 0.4f, 0.3f);
        add(temple, C / 2 + 30.0f, 62.0f, 1.0f, faceX(62.0f), 0.8f);
        add(colossus, C / 2 + 40.0f, -42.0f, 1.2f, faceZ(-42.0f) + 0.4f, 0.8f);
        add(room, C / 2 + 16.0f, -14.0f, 1.2f, PI + 0.6f, 0.0f);
        add(vase, C / 2 + 12.0f, 9.0f, 1.2f, 1.0f, 0.2f);
        add(naturalArch, 60.0f, -75.0f, 1.3f, 0.0f, 0.4f);

        // A temple podium standing empty: its whole portico hangs 14 m above it, still facing the trail
        add(podium, 110.0f, -20.0f, 1.0f, faceZ(-20.0f), 0.3f);
        add(portico, 110.0f, -20.0f, 1.0f, faceZ(-20.0f), 0.0f, 14.0f);
        ruins.back().drift = false;
        // A ring of standing stones with a huge boulder hanging over it like a captured moon
        for (int k = 0; k < 8; ++k) {
            float a = k * 2.0f * PI / 8.0f;
            add(monolith, 84.0f + 6.0f * std::cos(a), 22.0f + 6.0f * std::sin(a), 0.9f + 0.05f * (k % 3), a, 0.2f);
        }
        add(boulder, 84.0f, 22.0f, 2.2f, 0.0f, 0.0f, 20.0f);

        // 4. The outskirts: houses, tombs, towers, a toppled tower, a last arch on the trail
        add(house, 100.0f, 12.0f, 1.2f, faceZ(12.0f), 0.0f);
        add(house, 134.0f, 11.0f, 1.0f, faceZ(11.0f) + 0.3f, 0.0f);
        add(mastaba, 146.0f, -24.0f, 1.2f, faceZ(-24.0f), 0.0f);
        add(mastaba, 150.0f, 24.0f, 1.0f, faceZ(24.0f), 0.0f);
        add(sarcophagus, 135.0f, 7.0f, 1.0f, 0.3f, 0.1f);
        add(sarcophagus, 147.0f, -7.5f, 1.0f, 2.8f, 0.1f);
        add(tower, 84.0f, -30.0f, 1.2f, faceX(-30.0f), 0.15f);
        add(tower, 100.0f, 55.0f, 1.6f, faceX(55.0f), 0.2f);
        add(stump, 128.0f, 18.0f, 1.0f, faceX(18.0f) + 0.5f, 0.15f);
        add(fallen, 112.0f, 15.0f, 1.2f, 2.0f, 0.5f);
        add(arch, 140.0f, 0.0f, 1.0f, 0.0f, 0.0f);
        add(room, 136.0f, -16.0f, 1.0f, PI + 0.6f, 0.0f);
        add(rubble, 120.0f, -10.0f, 1.0f, 0.4f, 0.0f);
        add(drums, 96.0f, 9.0f, 1.0f, 1.3f, 0.2f);

        // The impossible part: pieces of the city hanging in the air
        add(arch2, 92.0f, -14.0f, 1.2f, 0.0f, 0.0f, 9.0f);
        add(drums, 18.0f, 13.0f, 1.0f, 0.0f, 0.0f, 7.0f);
        add(wall, 118.0f, 16.0f, 0.9f, 0.0f, 0.0f, 8.0f);
        add(rubble, 60.0f, -18.0f, 0.9f, 0.0f, 0.0f, 6.0f);
        for (int k = 0; k < 8; ++k)
            add(boulder, k * 19.0f + 3.0f, (k % 2 ? 1.0f : -1.0f) * (9.0f + 1.5f * k), 0.6f + 0.2f * (k % 4),
                0.0f, 0.0f, 5.0f + 1.0f * k);
    }

    // Far landmarks (Poly Haven scans, blender/scripts/build_backdrop_*.py): cliffs and mesas on the horizon,
    // big rock outcrops and desert trees 30-160 m from the trail. They use the same appear / crumble logic as
    // the ruins but with a longer 320 m pattern, so the horizon changes slowly while the camel travels.
    void buildBackdrop() {
        auto tinted = [&](const char* file, glm::vec3 tint) -> const Model& {
            Model& m = load(file, false);
            for (Mesh& me : m.meshes) me.color = glm::vec4(tint, 1.0f);   // lift dark scans towards sandstone
            return m;
        };
        const Model& cliff1  = tinted("bg_cliff_01.glb", {1.35f, 1.2f, 1.0f});   // front = +Z
        const Model& cliff2  = tinted("bg_cliff_02.glb", {1.35f, 1.2f, 1.0f});
        const Model& butte   = tinted("bg_boulder_06.glb", {1.1f, 1.05f, 0.95f}); // 1.9 m tall at scale 1
        const Model& mesa    = tinted("bg_rock_07.glb", {1.25f, 1.1f, 0.9f});
        const Model& ridge   = tinted("bg_rock_09.glb", {1.4f, 1.2f, 0.95f});
        const Model& outcrop = tinted("bg_boulder_02.glb", {1.2f, 1.1f, 0.95f});
        const Model& mound   = load("bg_boulder_05.glb", false);                  // already sand coloured
        const Model& stones  = tinted("bg_boulders_cluster.glb", {1.1f, 1.05f, 0.95f});
        const Model& quiver  = tinted("bg_quiver_tree_01.glb", {1.1f, 1.0f, 0.85f});
        const Model& deadQ   = tinted("bg_dead_quiver_trunk.glb", {1.15f, 1.0f, 0.8f});
        const Model& log     = tinted("bg_dead_tree_trunk_02.glb", {1.15f, 1.05f, 0.9f});

        // side > 0 = left of the traveller. Cliffs are turned so their open back never faces the trail:
        // yaw 0 on the left side, PI on the right side.
        auto add = [&](const Model& m, float offset, float side, float scale, float yaw, float sink) {
            Ruin r;
            r.node = propNode(m); r.model = &m; r.backdrop = true;
            r.pattern = 320.0f; r.offset = offset; r.side = side; r.scale = scale;
            r.alongTrail = true; r.yaw = yaw; r.sink = sink;
            ruins.push_back(r);
        };
        const float L = 0.0f, R = PI;   // face the trail from the left / right
        add(cliff2,  40.0f,  140.0f, 1.3f, L, 2.0f);
        add(cliff1, 120.0f, -100.0f, 1.3f, R, 1.3f);
        add(cliff2, 210.0f, -160.0f, 1.1f, R, 1.7f);
        add(cliff1, 275.0f,   95.0f, 1.4f, L, 1.4f);
        add(butte,   15.0f,  -70.0f, 9.0f, 1.6f, 0.45f);
        add(butte,  180.0f,   75.0f, 11.0f, 0.4f, 0.55f);
        add(mesa,    90.0f,  110.0f, 13.0f, 1.6f, 0.65f);
        add(mesa,   245.0f, -120.0f, 14.0f, 1.2f, 0.7f);
        add(ridge,  150.0f,  130.0f, 14.0f, 1.5f, 1.4f);
        add(ridge,  300.0f,  -90.0f, 12.0f, 1.7f, 1.2f);
        add(outcrop, 60.0f,  -55.0f, 7.0f, 0.8f, 1.1f);
        add(outcrop,200.0f,   50.0f, 8.0f, 2.4f, 1.2f);
        add(mound,  100.0f,   45.0f, 6.0f, 0.3f, 0.3f);
        add(mound,  262.0f,  -45.0f, 5.0f, 2.0f, 0.25f);
        add(stones, 128.0f,  -82.0f, 5.0f, 0.5f, 0.25f);
        add(stones,  36.0f,  112.0f, 5.0f, 1.9f, 0.25f);
        // Groves of quiver trees and dead trunks on the dune crests, nearer the trail
        add(quiver,  70.0f,   35.0f, 1.2f, 0.0f, 0.2f);
        add(quiver,  74.0f,   39.0f, 1.0f, 2.1f, 0.2f);
        add(quiver,  77.0f,   33.0f, 1.4f, 4.0f, 0.2f);
        add(deadQ,   81.0f,   30.0f, 1.3f, 1.0f, 0.25f);
        add(quiver, 225.0f,  -32.0f, 1.3f, 1.3f, 0.2f);
        add(quiver, 229.0f,  -37.0f, 1.0f, 3.3f, 0.2f);
        add(deadQ,  233.0f,  -28.0f, 1.5f, 0.6f, 0.3f);
        add(quiver, 160.0f,  -40.0f, 1.2f, 5.0f, 0.2f);
        add(deadQ,  300.0f,   34.0f, 1.2f, 2.6f, 0.25f);
        add(log,    140.0f,   25.0f, 3.0f, 0.4f, 1.6f);
        add(log,      8.0f,  -24.0f, 1.5f, 2.2f, 0.4f);
        // A walled citadel far away on the left, its gate (+Z) facing the trail
        add(load("sf_set_palace.glb", false), 170.0f, 170.0f, 0.8f, L, 0.4f);
        // Stepped pyramids (stairs = +Z) on the horizon
        const Model& pyramid = tinted("step_pyramid.glb", {2.0f, 1.6f, 1.15f});
        add(pyramid,  60.0f, -135.0f, 1.3f, R, 0.5f);
        add(pyramid, 195.0f,  120.0f, 1.0f, L, 0.5f);
    }

    // =====================================================================================================
    // One simulation step (dt = simulation seconds; 0 when paused, but the transforms are still updated)
    // =====================================================================================================
    void update(float dt) {
        if (dt > 0.0f) {
            simTime += dt;
            float speed = WALK_SPEED * (1.0f + 0.12f * std::sin(2.0f * phi));   // pace gait surges twice a stride
            camelX += speed * dt / std::sqrt(1.0f + trailSlope(camelX) * trailSlope(camelX));
            phi += 2.0f * PI * (WALK_SPEED / STRIDE) * dt;
        }
        placeCamel();
        animateCamel();
        animateRider(dt);
        animateRocks();

        // Update the whole transform tree (parent -> child)
        glm::mat4 identity(1.0f);
        camelRoot->update(identity);                   // camel + rider (+ the rider camera reads from it)
        rockRing->update(identity);
        for (Ruin& r : ruins) {
            r.update(dt, camelX, simTime, dust);
            r.node->update(identity);
        }
        updateLantern(dt);
        startFootsteps();
        dust.update(dt);
    }

    // The camel stands on the liquid sand at its point on the trail, facing along it and tilted with the slope
    void placeCamel() {
        camelDir = glm::normalize(glm::vec3(1.0f, 0.0f, trailSlope(camelX)));
        camelPos = glm::vec3(camelX, 0.0f, trailZ(camelX));
        auto h = [&](const glm::vec3& p) { return sandHeight(p.x, p.z, simTime); };
        camelPos.y = h(camelPos) + 0.025f * std::cos(2.0f * phi);       // body rises and falls twice a stride
        slopePitch = std::atan2(h(camelPos + camelDir) - h(camelPos - camelDir), 2.0f);
        heading = std::atan2(camelDir.z, camelDir.x);
        camelRoot->base = glm::translate(glm::mat4(1.0f), camelPos) *
                          glm::rotate(glm::mat4(1.0f), -heading, glm::vec3(0, 1, 0)) *
                          glm::rotate(glm::mat4(1.0f), slopePitch, glm::vec3(0, 0, 1));
    }

    // ---- Procedural animation, driven by the gait phase phi ----
    // Camel frame: faces +X, Y up, so the legs swing about Z. Explorer frame: faces +Z, left = +X,
    // so his joints pitch about X, roll about Z and twist about Y. Every angle is relative to the rest pose.
    void animateCamel() {
        float t = simTime;
        // Pace: both legs on one side move together; the hind legs lag a little.
        for (int l = 0; l < 4; ++l) {
            float ph = phi + LEG_PHASE[l];
            float lift = std::max(0.0f, std::cos(ph));            // 0 on the ground, 1 mid-swing
            bool front = l < 2;
            leg[l][0]->angle.z = (front ? 0.38f : 0.32f) * std::sin(ph);              // hip/shoulder swing
            leg[l][1]->angle.z = front ? -1.0f * lift : 0.65f * lift;                 // knee folds back / hock forward
            leg[l][2]->angle.z = (front ? -0.45f : -0.55f) * lift * lift;             // the foot curls as it lifts
        }
        spine->angle = {0.09f * std::sin(phi), 0.0f, 0.015f * std::sin(2 * phi + 0.5f)};  // pacing camels roll side to side
        neck1->angle.z = 0.07f * std::sin(2 * phi + 0.6f);                             // the neck pumps twice a stride
        neck2->angle.z = -0.04f * std::sin(2 * phi + 1.0f);
        head->angle = {0.0f, 0.10f * std::sin(0.25f * t),                              // keeps the head level, looks around
                       -0.85f * (neck1->angle.z + neck2->angle.z) + 0.03f * std::sin(0.7f * t)};
        tail->angle = {0.30f * std::sin(phi + 0.4f) + 0.12f * std::sin(0.9f * t), 0.0f, 0.06f * std::sin(2 * phi)};
    }

    // [Advanced: secondary motion (springs)] The rider's torso, head and cloak lag behind the camel
    // through damped springs (spring.h); the lantern below is a damped pendulum.
    void animateRider(float dt) {
        float t = simTime;
        // The seat lifts slightly with the camel's back
        explorer->base = explorerSeat * glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.04f * std::max(0.0f, std::sin(2 * phi - 0.9f)), 0.0f));

        // 1) Pelvis: sits on the saddle. It rocks fore-aft twice per stride, rolls towards the side whose legs
        //    are on the ground, and twists a little with each step (pace gait).
        hips->angle = {0.16f * std::sin(2 * phi - 0.6f), 0.08f * std::sin(phi), 0.09f * std::sin(phi - 0.3f)};

        // 2) Torso: an inverted pendulum held upright by muscles (a spring) on top of the pelvis.
        //    target = lean against the pelvis tilt, lean forward on uphill slopes, plus a slow irregular sway
        //    (sum of two unrelated sines) so it never looks like a machine;
        //    force  = inertia: when the saddle accelerates forwards the torso tips backwards.
        saddle.update(glm::vec3(explorer->world[3]), dt);
        glm::mat3 R(explorer->world);
        for (int c = 0; c < 3; ++c) R[c] = glm::normalize(R[c]);
        glm::vec3 acc = glm::transpose(R) * saddle.acc;            // saddle acceleration in the rider's frame
        const float TORSO_LEN = 0.5f;
        float sway = 0.04f * std::sin(0.37f * t) + 0.03f * std::sin(0.83f * t + 1.0f);
        torsoPitch.update(-0.75f * hips->angle.x + 0.6f * slopePitch, dt, -acc.z / TORSO_LEN);
        torsoRoll.update(-0.75f * hips->angle.z + sway, dt, acc.x / TORSO_LEN);
        // Lower back takes 35 % of the bend, the chest 65 % (a little later). The chest twists against the
        // pelvis (counter-rotation, like walking) and rises with breathing.
        spineE->angle = {0.35f * torsoPitch.x, 0.0f, 0.35f * torsoRoll.x};
        chest->angle = {chestPitch.update(0.65f * torsoPitch.x, dt) + 0.02f * std::sin(1.6f * t),
                        -0.12f * std::sin(phi),
                        chestRoll.update(0.65f * torsoRoll.x, dt)};

        // 3) Head: cancels half of the body's tilt and looks at a new random direction every few seconds,
        //    turning there smoothly through a critically damped spring.
        lookTimer -= dt;
        if (lookTimer <= 0.0f) {
            lookTimer = rnd(2.0f, 5.0f);
            lookYawTarget = rnd(-0.8f, 0.8f);
            lookPitchTarget = rnd(-0.2f, 0.1f);
        }
        headE->angle = {-0.5f * (hips->angle.x + spineE->angle.x + chest->angle.x) + lookPitch.update(lookPitchTarget, dt),
                        lookYaw.update(lookYawTarget, dt) - 0.5f * (hips->angle.y + chest->angle.y),
                        -0.5f * (hips->angle.z + spineE->angle.z + chest->angle.z)};

        // 4) Arms and legs: riding posture + small follow-through. The arms stay calm because the hands hold
        //    the reins and the lantern (the lantern pendulum is driven by the hand's acceleration).
        for (int i = 0; i < 2; ++i) shoulder[i]->angle.z = 0.06f * std::sin(2 * phi - 1.6f);
        upperArm[0]->angle.x = POSE_ARM + 0.05f * std::sin(2 * phi - 1.8f) - 0.5f * (spineE->angle.x + chest->angle.x);   // lantern arm
        forearm[0]->angle.x = POSE_ELBOW + 0.07f * std::sin(2 * phi - 2.1f);
        upperArm[1]->angle.x = POSE_ARM + 0.10f * std::sin(phi + 0.5f);    // reins hand follows the camel's head
        forearm[1]->angle.x = POSE_ELBOW + 0.12f * std::sin(phi + 0.2f);
        hand[1]->angle.x = 0.08f * std::sin(phi);
        for (int i = 0; i < 2; ++i) {                                       // legs hang along the flanks, lagging behind
            float side = i * PI;
            thigh[i]->angle.x = POSE_THIGH + 0.04f * std::sin(phi + side);
            shin[i]->angle.x = POSE_KNEE + 0.24f * std::sin(phi - 0.8f + side);
            foot[i]->angle.x = 0.12f * std::sin(phi - 1.3f + side);
        }

        // 5) Cloak (3 bones on the chest): first cancel the torso's lean so it
        //    keeps hanging straight down, then a soft spring lets it swing back when the saddle surges forward
        //    and sideways when it rolls, plus a little wind. +x swings the hem away from the back.
        const float CLOAK_LEN = 0.9f;
        glm::vec3 lean = hips->angle + spineE->angle + chest->angle;
        float swingX = cloakPitch.update(0.06f + 0.03f * std::sin(0.9f * t), dt, acc.z / CLOAK_LEN);
        float swingZ = cloakRoll.update(0.0f, dt, -acc.x / CLOAK_LEN);
        for (int k = 0; k < 3; ++k) {
            float out = k == 0 ? 0.0f : (k == 1 ? 1.0f : -1.0f);       // Back, L (+x side), R
            float flare = out * (0.04f + 0.03f * std::sin(phi + k));     // side panels open a little each stride
            cloak[k]->angle = {std::max(-0.05f, -lean.x + swingX * (1.0f + 0.15f * k)), 0.0f,
                               -lean.z + swingZ + flare};
        }
    }

    // The ring of rocks follows the traveller (parent), each rock spins and bobs (child)
    void animateRocks() {
        float t = simTime;
        rockRing->base = glm::translate(glm::mat4(1.0f), glm::vec3(camelPos.x, 0.0f, camelPos.z));
        rockRing->angle.y = 0.12f * t;
        for (int k = 0; k < NROCKS; ++k) {
            rocks[k]->angle = {0.3f * t + k, 0.2f * t * (1 + k * 0.3f), 0.0f};
            rocks[k]->base[3][1] = ROCK_HEIGHT[k] + 0.5f * std::sin(0.8f * t + k * 1.7f);
        }
    }

    // Lantern = a damped pendulum hanging from the left hand. The hand's acceleration (camel steps,
    // rider's bob) drives the swing, so it lags and sways naturally instead of following a sine.
    void updateLantern(float dt) {
        glm::vec3 h = glm::vec3(hand[0]->frame() * glm::vec4(0.0f, -0.08f, 0.03f, 1.0f));   // inside the fist
        handTracker.update(h, dt);
        if (dt > 0.0f) {
            // Strong damping and only part of the hand's acceleration: a heavy lantern held firmly swings gently
            const float g = 9.81f, len = 0.25f, damping = 5.0f, push = 0.35f;
            const int steps = 4;
            for (int s = 0; s < steps; ++s) {                                 // semi-implicit Euler substeps
                float d = dt / steps;
                glm::vec2 a = -(g / len) * glm::sin(swing) - damping * swingVel -
                              push * glm::vec2(handTracker.acc.x, handTracker.acc.z) / len * glm::cos(swing);
                swingVel += a * d;
                swing = glm::clamp(swing + swingVel * d, glm::vec2(-0.35f), glm::vec2(0.35f));   // never more than 20 deg
            }
        }
        // swing.x moves the lantern towards +X, swing.y towards +Z (world axes)
        lantern->base = glm::translate(glm::mat4(1.0f), h) *
                        glm::rotate(glm::mat4(1.0f), swing.x, glm::vec3(0, 0, 1)) *
                        glm::rotate(glm::mat4(1.0f), -swing.y, glm::vec3(1, 0, 0)) *
                        glm::rotate(glm::mat4(1.0f), -heading, glm::vec3(0, 1, 0));
        lantern->update(glm::mat4(1.0f));
    }

    // A foot lands when its leg stops swinging forward (cos of its phase turns negative):
    // start a ripple there and kick up a puff of sand.
    void startFootsteps() {
        for (int l = 0; l < 4; ++l) {
            bool inAir = std::cos(phi + LEG_PHASE[l]) > 0.0f;
            if (legInAir[l] && !inAir) {
                glm::vec3 foot = leg[l][2]->jointPos();     // the foot bone sits on the ground
                ripples[nextRipple] = glm::vec4(foot.x, foot.z, simTime, 1.0f);
                nextRipple = (nextRipple + 1) % MAX_RIPPLES;
                for (int k = 0; k < 14; ++k) {
                    float a = rnd(0.0f, 2.0f * PI), sp = rnd(0.3f, 0.9f);
                    dust.emit(foot + glm::vec3(0.0f, 0.05f, 0.0f), glm::vec3(sp * std::cos(a), rnd(0.4f, 1.0f), sp * std::sin(a)),
                              glm::vec3(0.95f, 0.72f, 0.48f), rnd(0.04f, 0.09f), rnd(0.8f, 1.6f));
                }
            }
            legInAir[l] = inAir;
        }
    }

private:
    std::map<std::string, Node*> camelBones, explorerBones;   // bones by name (from the .glb files)
};

#pragma once
// [Advanced: skinning + scene graph] Scene graph for hierarchical animation.
//
// Each node is one joint (or a bone of a skeleton). It rotates about `pivot` and inherits all of
// its parent's motion:
//
//   world = parentWorld * base * T(pivot) * R(angle) * T(-pivot)
//
// Rotating a thigh moves its shin (child); rotating the camel's spine moves the explorer + lantern.
// Skinned meshes (camel, explorer) are bent on the GPU by the world matrices of their bone nodes.
#include "model.h"
#include <deque>
#include <map>
#include <vector>

struct Node;

// The bones of one skinned model: bone i is driven by node bones[i]
struct Skin {
    const Model* model = nullptr;
    std::vector<const Node*> bones;
};

struct Node {
    std::vector<const Mesh*> meshes;   // drawn in this node's frame (or skinned by `skin`)
    std::vector<Node*> children;
    Node* parent = nullptr;
    const Skin* skin = nullptr;        // set on the node that holds a skinned mesh
    glm::mat4 base{1.0f};              // placement relative to the parent (bone rest pose for skeletons)
    glm::mat3 axes{1.0f};              // rest orientation in the rig's frame: angles are given in rig axes
    glm::vec3 pivot{0.0f};             // joint position
    glm::vec3 angle{0.0f};             // Euler angles (rad), written by the animation each frame
    glm::vec3 extra{0.0f};             // added on top by the user in joint mode (arrow keys)
    glm::mat4 world{1.0f};             // result of update()

    Node* add(Node* c) { children.push_back(c); c->parent = this; return c; }

    bool isUnder(const Node* ancestor) const {
        for (const Node* p = this; p; p = p->parent) if (p == ancestor) return true;
        return false;
    }

    void update(const glm::mat4& parentWorld) {
        glm::vec3 a = angle + extra;
        glm::mat3 R = glm::mat3(glm::rotate(glm::mat4(1.0f), a.z, glm::vec3(0, 0, 1)) *
                                glm::rotate(glm::mat4(1.0f), a.y, glm::vec3(0, 1, 0)) *
                                glm::rotate(glm::mat4(1.0f), a.x, glm::vec3(1, 0, 0)));
        // A bone's own axes are rolled arbitrarily; express R in the rig's axes instead
        // (e.g. "X = the explorer's left-right axis" for every explorer bone)
        glm::mat4 L = glm::mat4(glm::transpose(axes) * R * axes);
        world = parentWorld * base * glm::translate(glm::mat4(1.0f), pivot) * L * glm::translate(glm::mat4(1.0f), -pivot);
        for (Node* c : children) c->update(world);
    }

    // `selected` (joint mode) and everything below it is drawn highlighted
    void draw(GLuint program, const Node* selected = nullptr, bool highlight = false) const {
        highlight = highlight || this == selected;
        glUniformMatrix4fv(glGetUniformLocation(program, "uModel"), 1, GL_FALSE, &world[0][0]);
        glUniform1i(glGetUniformLocation(program, "uHighlight"), highlight);
        if (skin) {   // skinning matrices: bone world * inverse bind
            std::vector<glm::mat4> M(skin->bones.size());
            for (size_t i = 0; i < M.size(); ++i) M[i] = skin->bones[i]->world * skin->model->boneOffsets[i];
            glUniformMatrix4fv(glGetUniformLocation(program, "uBones"), (GLsizei)M.size(), GL_FALSE, &M[0][0][0]);
            std::vector<float> hl(skin->bones.size());   // joint mode: bones inside the selected subtree glow
            for (size_t i = 0; i < hl.size(); ++i) hl[i] = selected && skin->bones[i]->isUnder(selected) ? 1.0f : 0.0f;
            glUniform1fv(glGetUniformLocation(program, "uBoneHighlight"), (GLsizei)hl.size(), hl.data());
        }
        for (const Mesh* m : meshes) {
            glUniform1i(glGetUniformLocation(program, "uSkinned"), m->skinned);
            drawMesh(*m, program);
        }
        glUniform1i(glGetUniformLocation(program, "uSkinned"), 0);
        for (const Node* c : children) c->draw(program, selected, highlight);
    }

    // World matrix with the rig's axes instead of the bone's own (rolled) axes, e.g. for attaching things
    glm::mat4 frame() const { return world * glm::mat4(glm::transpose(axes)); }

    glm::vec3 jointPos() const { return glm::vec3(world * glm::vec4(pivot, 1.0f)); }

    // Skeleton overlay: one line from this joint to each child joint (world space)
    void skeleton(std::vector<glm::vec3>& lines, std::vector<glm::vec3>& joints) const {
        joints.push_back(jointPos());
        for (const Node* c : children) {
            if (!c->meshes.empty() && c->children.empty() && c->skin) continue;   // skip the skinned mesh node
            lines.push_back(jointPos());
            lines.push_back(c->jointPos());
            c->skeleton(lines, joints);
        }
    }
};

// Turn the node tree of a model (loaded with keepHierarchy) into Nodes. Each file node keeps its
// own transform as `base`; bone nodes sit on their joint, so pivot stays 0 and the animation rotates
// them about that joint. `byName` lets the animation find bones; skinned meshes get a Skin.
inline Node* buildNodeTree(const Model& m, std::deque<Node>& pool, std::deque<Skin>& skins,
                           std::map<std::string, Node*>& byName, int i = 0, glm::mat3 parentAxes = glm::mat3(1.0f)) {
    pool.emplace_back();
    Node* n = &pool.back();
    n->base = m.nodes[i].local;
    glm::mat3 r = parentAxes * glm::mat3(n->base);
    for (int c = 0; c < 3; ++c) r[c] = glm::normalize(r[c]);   // rotation only
    n->axes = r;
    for (int k : m.nodes[i].meshes) n->meshes.push_back(&m.meshes[k]);
    byName[m.nodes[i].name] = n;
    for (int c : m.nodes[i].children) n->add(buildNodeTree(m, pool, skins, byName, c, r));
    if (i == 0 && !m.boneNames.empty()) {   // whole tree built: bind the skeleton to its nodes
        skins.emplace_back();
        skins.back().model = &m;
        for (const std::string& b : m.boneNames) skins.back().bones.push_back(byName.at(b));
        for (Node& p : pool)
            for (const Mesh* me : p.meshes)
                if (me->skinned && me >= &m.meshes.front() && me <= &m.meshes.back()) p.skin = &skins.back();
    }
    return n;
}

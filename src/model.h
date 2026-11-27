#pragma once
// Model loading with Assimp: meshes, materials, textures, node tree and skin weights.
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <assimp/Importer.hpp>
#include <assimp/scene.h>
#include <assimp/postprocess.h>

#include <algorithm>
#include <cstddef>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <string>
#include <vector>

// stb_image implementation is defined in EXACTLY one place (this file is only included from main.cpp)
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

struct Vertex {
    glm::vec3 pos;
    glm::vec3 normal;
    glm::vec2 uv;
    glm::ivec4 bones{0};          // skinning: up to 4 bones per vertex (indices into Model::boneNames)
    glm::vec4 weights{0.0f};      // their weights (sum = 1); all 0 for meshes without a skeleton
};

struct Mesh {
    GLuint vao = 0, vbo = 0, ebo = 0, tex = 0;
    GLsizei indexCount = 0;
    // Blinn-Phong material
    glm::vec4 color{0.8f, 0.7f, 0.55f, 1.0f};
    float spec = 0.2f, shininess = 32.0f;
    glm::vec3 emissive{0.0f};
    bool skinned = false;         // deformed by a skeleton (see Skin in node.h)
};

// Upload vertex/index data to the GPU
inline Mesh uploadMesh(const std::vector<Vertex>& verts, const std::vector<unsigned>& idx) {
    Mesh m;
    m.indexCount = (GLsizei)idx.size();
    glGenVertexArrays(1, &m.vao);
    glGenBuffers(1, &m.vbo);
    glGenBuffers(1, &m.ebo);

    glBindVertexArray(m.vao);
    glBindBuffer(GL_ARRAY_BUFFER, m.vbo);
    glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(Vertex), verts.data(), GL_STATIC_DRAW);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m.ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.size() * sizeof(unsigned), idx.data(), GL_STATIC_DRAW);

    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void*)offsetof(Vertex, pos));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void*)offsetof(Vertex, normal));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void*)offsetof(Vertex, uv));
    glEnableVertexAttribArray(3);
    glVertexAttribIPointer(3, 4, GL_INT, sizeof(Vertex), (void*)offsetof(Vertex, bones));
    glEnableVertexAttribArray(4);
    glVertexAttribPointer(4, 4, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void*)offsetof(Vertex, weights));
    glBindVertexArray(0);
    return m;
}

// Set material uniforms and draw one mesh (caller sets uModel)
inline void drawMesh(const Mesh& m, GLuint program) {
    glUniform1i(glGetUniformLocation(program, "uHasTex"), m.tex != 0);
    glUniform4fv(glGetUniformLocation(program, "uColor"), 1, &m.color[0]);
    glUniform1f(glGetUniformLocation(program, "uSpec"), m.spec);
    glUniform1f(glGetUniformLocation(program, "uShininess"), m.shininess);
    glUniform3fv(glGetUniformLocation(program, "uEmissive"), 1, &m.emissive[0]);
    if (m.tex) {
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, m.tex);
        glUniform1i(glGetUniformLocation(program, "uTex"), 0);
    }
    glBindVertexArray(m.vao);
    glDrawElements(GL_TRIANGLES, m.indexCount, GL_UNSIGNED_INT, nullptr);
    glBindVertexArray(0);
}


// [Texture mapping: loading] Load an image file (or the compressed bytes embedded in a .glb) into an OpenGL texture.
// GL_REPEAT lets UVs outside [0,1] tile the image; mipmaps + trilinear filtering keep far-away
// (minified) texels from shimmering. Each file is loaded only once (cache).
inline GLuint loadTexture(const std::string& file, const aiTexture* embedded = nullptr) {
    static std::map<std::string, GLuint> texCache;
    auto it = texCache.find(file);
    if (it != texCache.end()) return it->second;

    stbi_set_flip_vertically_on_load(true);   // images start at the top row, OpenGL's v = 0 is the bottom
    int w, h, n;
    unsigned char* data = embedded
        ? stbi_load_from_memory((const unsigned char*)embedded->pcData,
                                (int)embedded->mWidth, &w, &h, &n, 4)   // glTF embeds compressed images (mHeight == 0)
        : stbi_load(file.c_str(), &w, &h, &n, 4);
    if (!data) {
        std::cerr << "Texture failed: " << file << "\n";
        return 0;
    }
    GLuint id;
    glGenTextures(1, &id);
    glBindTexture(GL_TEXTURE_2D, id);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
    glGenerateMipmap(GL_TEXTURE_2D);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    stbi_image_free(data);
    texCache[file] = id;
    return id;
}

class Model {
public:
    std::vector<Mesh> meshes;
    glm::vec3 minB{ std::numeric_limits<float>::max() };
    glm::vec3 maxB{ -std::numeric_limits<float>::max() };

    // Node tree of the file (only filled when loaded with keepHierarchy); nodes[0] is the root
    struct NodeInfo {
        std::string name;
        glm::mat4 local;              // transform relative to the parent node
        std::vector<int> meshes;      // indices into `meshes`
        std::vector<int> children;    // indices into `nodes`
    };
    std::vector<NodeInfo> nodes;

    // Skeleton (only for skinned models): bone i is the node named boneNames[i];
    // boneOffsets[i] is its inverse bind matrix (mesh space -> bone space at rest)
    std::vector<std::string> boneNames;
    std::vector<glm::mat4> boneOffsets;

    // keepHierarchy = false: bake node transforms into the vertices (static props).
    // keepHierarchy = true : keep each node's own transform so parts can be animated as a hierarchy.
    bool load(const std::string& path, bool keepHierarchy = false) {
        Assimp::Importer importer;
        unsigned flags = aiProcess_Triangulate | aiProcess_GenSmoothNormals | aiProcess_JoinIdenticalVertices |
                         aiProcess_LimitBoneWeights;   // at most 4 bones per vertex
        if (!keepHierarchy) flags |= aiProcess_PreTransformVertices;
        const aiScene* scene = importer.ReadFile(path, flags);
        if (!scene || !scene->mRootNode) {
            std::cerr << "Assimp error: " << importer.GetErrorString() << "\n";
            return false;
        }

        for (unsigned i = 0; i < scene->mNumMeshes; ++i)
            meshes.push_back(buildMesh(scene->mMeshes[i], scene, path));
        if (keepHierarchy) addNode(scene->mRootNode);

        std::cout << "Loaded " << meshes.size() << " meshes, " << nodes.size() << " nodes from " << path << "\n";
        return true;
    }

private:
    int boneId(const std::string& name, const glm::mat4& offset) {
        for (size_t i = 0; i < boneNames.size(); ++i)
            if (boneNames[i] == name) return (int)i;
        boneNames.push_back(name);
        boneOffsets.push_back(offset);
        return (int)boneNames.size() - 1;
    }

    int addNode(const aiNode* an) {
        int id = (int)nodes.size();
        nodes.push_back({an->mName.C_Str(), glm::transpose(glm::make_mat4(&an->mTransformation.a1)), {}, {}});
        for (unsigned i = 0; i < an->mNumMeshes; ++i) nodes[id].meshes.push_back((int)an->mMeshes[i]);
        for (unsigned i = 0; i < an->mNumChildren; ++i) {
            int c = addNode(an->mChildren[i]);
            nodes[id].children.push_back(c);
        }
        return id;
    }

    Mesh buildMesh(const aiMesh* am, const aiScene* scene, const std::string& path) {
        std::vector<Vertex> verts(am->mNumVertices);
        for (unsigned i = 0; i < am->mNumVertices; ++i) {
            verts[i].pos = { am->mVertices[i].x, am->mVertices[i].y, am->mVertices[i].z };
            verts[i].normal = am->HasNormals()
                ? glm::vec3(am->mNormals[i].x, am->mNormals[i].y, am->mNormals[i].z)
                : glm::vec3(0.0f, 1.0f, 0.0f);
            verts[i].uv = am->HasTextureCoords(0)
                ? glm::vec2(am->mTextureCoords[0][i].x, am->mTextureCoords[0][i].y)
                : glm::vec2(0.0f);
            minB = glm::min(minB, verts[i].pos);
            maxB = glm::max(maxB, verts[i].pos);
        }

        std::vector<unsigned> idx;
        for (unsigned f = 0; f < am->mNumFaces; ++f)
            for (unsigned k = 0; k < am->mFaces[f].mNumIndices; ++k)
                idx.push_back(am->mFaces[f].mIndices[k]);

        // Skin weights: each aiBone lists the vertices it moves; store them per vertex (max 4)
        for (unsigned b = 0; b < am->mNumBones; ++b) {
            const aiBone* bone = am->mBones[b];
            int id = boneId(bone->mName.C_Str(), glm::transpose(glm::make_mat4(&bone->mOffsetMatrix.a1)));
            for (unsigned k = 0; k < bone->mNumWeights; ++k) {
                Vertex& v = verts[bone->mWeights[k].mVertexId];
                for (int s = 0; s < 4; ++s)
                    if (v.weights[s] == 0.0f) { v.bones[s] = id; v.weights[s] = bone->mWeights[k].mWeight; break; }
            }
        }
        for (Vertex& v : verts) {   // renormalise (LimitBoneWeights may have dropped small weights)
            float sum = v.weights.x + v.weights.y + v.weights.z + v.weights.w;
            if (sum > 0.0f) v.weights /= sum;
        }

        Mesh mesh = uploadMesh(verts, idx);
        mesh.skinned = am->mNumBones > 0;

        // [Texture mapping: model UVs] material base colour + texture (if any); the per-vertex UVs read above map it
        const aiMaterial* mat = scene->mMaterials[am->mMaterialIndex];
        aiColor4D c;
        if (mat->Get(AI_MATKEY_BASE_COLOR, c) == AI_SUCCESS ||
            mat->Get(AI_MATKEY_COLOR_DIFFUSE, c) == AI_SUCCESS)
            mesh.color = { c.r, c.g, c.b, c.a };

        aiTextureType type = mat->GetTextureCount(aiTextureType_BASE_COLOR)
                                 ? aiTextureType_BASE_COLOR : aiTextureType_DIFFUSE;
        aiString p;
        if (mat->GetTextureCount(type) > 0 && mat->GetTexture(type, 0, &p) == AI_SUCCESS) {
            const aiTexture* embedded = scene->GetEmbeddedTexture(p.C_Str());
            // embedded names ("*0") repeat in every .glb, so prefix them with the model file for the cache
            std::string file = embedded ? path + p.C_Str() : path.substr(0, path.find_last_of("/\\") + 1) + p.C_Str();
            mesh.tex = loadTexture(file, embedded);
        }

        return mesh;
    }
};

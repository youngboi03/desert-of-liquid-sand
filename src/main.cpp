// Desert of Liquid Sand - CS7GV6 Project 1.
// main.cpp: window, keyboard / mouse, cameras, lights, the two render passes (shadow map + scene) and the
// skeleton overlay. WHAT is in the scene and HOW it moves is in world.h.
//
// Where each feature lives:
//   Lighting and shading  - lights: uploadFrameUniforms() here; Blinn-Phong, Phong / Gouraud / flat: common.glsl,
//                           scene.vert, scene.frag
//   Texture mapping       - loading: model.h loadTexture(); sand tiling, normal map, galaxy: scene.frag
//   Advanced features     - noise dissolve: ruins.h + scene.frag;  shadow mapping: shadow.h + renderShadowPass();
//                           particles: particles.h;  liquid sand: sand.h + scene.vert;  scene graph and skinning:
//                           node.h + world.h;  secondary motion (springs): spring.h + world.h;
//                           endless journey (ruin recycling): ruins.h ahead()
//
// The main loop reads like a table of contents:
//   handleInput -> world.update -> updateCamera -> uploadFrameUniforms
//   -> renderShadowPass -> renderScenePass -> drawSkeletonOverlay
#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "world.h"
#include "camera.h"
#include "shadow.h"

static const int WIN_W = 1280;
static const int WIN_H = 720;

// What is being drawn: tells the shaders which code path to use (same numbers as MODE_* in common.glsl)
enum DrawMode { MODE_OBJECT = 0, MODE_SKY = 1, MODE_SAND = 2, MODE_OVERLAY = 3 };

// Feature switches (F1..F8) and display options. Everything is on by default.
struct Settings {
    bool sun = true, points = true, spec = true, spot = true;   // lights (F1, F2, F3, F5)
    bool textures = true, normalMap = true, shadows = true;     // F6, F7, F8
    int shading = 0;                                            // F4: 0 Phong, 1 Gouraud, 2 flat
    bool paused = false, wireframe = false, skeleton = false;
    float speed = 1.0f;                                         // animation speed (- / =)
};

// Joint mode: pick a joint with Tab and rotate it with the arrow keys; all its children follow.
// axis = the joint's main swing axis in its own frame (camel legs swing about Z, the explorer's about X)
struct Joint { const char* name; Node* node; int axis; };

// ---------------- mouse (orbit / look) ----------------
static Camera cam;
static bool dragging = false;
static double lastX = 0, lastY = 0;

static void framebufferSizeCallback(GLFWwindow*, int w, int h) { glViewport(0, 0, w, h); }
static void mouseButtonCallback(GLFWwindow* window, int button, int action, int) {
    if (button == GLFW_MOUSE_BUTTON_LEFT) {
        dragging = action == GLFW_PRESS;
        glfwGetCursorPos(window, &lastX, &lastY);
    }
}
static void cursorCallback(GLFWwindow*, double x, double y) {
    if (dragging) cam.drag((float)(x - lastX), (float)(y - lastY));
    lastX = x; lastY = y;
}
static void scrollCallback(GLFWwindow*, double, double dy) { cam.scroll((float)dy); }

// ---------------- shaders ----------------
static std::string readFile(const std::string& path) {
    std::ifstream f(path);
    if (!f) {
        std::cerr << "Cannot open file: " << path << "\n";
        return "";
    }
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static GLuint compileShader(GLenum type, std::string src, const std::string& name) {
    // Insert the shared lighting code (common.glsl) right after the #version line
    size_t eol = src.find('\n');
    src.insert(eol + 1, readFile(SHADER_DIR "common.glsl"));
    GLuint s = glCreateShader(type);
    const char* c = src.c_str();
    glShaderSource(s, 1, &c, nullptr);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, 1024, nullptr, log);
        std::cerr << "Shader compile error (" << name << "):\n" << log << "\n";
    }
    return s;
}

static GLuint createProgram(const std::string& vertPath, const std::string& fragPath) {
    GLuint vs = compileShader(GL_VERTEX_SHADER, readFile(vertPath), vertPath);
    GLuint fs = compileShader(GL_FRAGMENT_SHADER, readFile(fragPath), fragPath);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetProgramInfoLog(prog, 1024, nullptr, log);
        std::cerr << "Program link error:\n" << log << "\n";
    }
    glDeleteShader(vs);
    glDeleteShader(fs);
    return prog;
}

int main() {
    // ---------------- window + OpenGL ----------------
    if (!glfwInit()) {
        std::cerr << "Failed to init GLFW\n";
        return -1;
    }
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    GLFWwindow* window = glfwCreateWindow(WIN_W, WIN_H, "Desert of Liquid Sand", nullptr, nullptr);
    if (!window) {
        std::cerr << "Failed to create window\n";
        glfwTerminate();
        return -1;
    }
    glfwMakeContextCurrent(window);
    glfwSetFramebufferSizeCallback(window, framebufferSizeCallback);
    glfwSetMouseButtonCallback(window, mouseButtonCallback);
    glfwSetCursorPosCallback(window, cursorCallback);
    glfwSetScrollCallback(window, scrollCallback);
    if (!gladLoadGLLoader((GLADloadproc)glfwGetProcAddress)) {
        std::cerr << "Failed to init GLAD\n";
        return -1;
    }
    glEnable(GL_DEPTH_TEST);

    GLuint program = createProgram(SHADER_DIR "scene.vert", SHADER_DIR "scene.frag");
    GLuint dustProgram = createProgram(SHADER_DIR "particle.vert", SHADER_DIR "particle.frag");
    auto loc = [&](const char* name) { return glGetUniformLocation(program, name); };

    // ---------------- textures: each sampler has its own texture unit, set once ----------------
    ShadowMap shadow;
    shadow.init();
    glUseProgram(program);
    glUniform1i(loc("uTex"), 0);          // model texture (bound per mesh in drawMesh)
    glUniform1i(loc("uShadowMap"), 1);
    glUniform1i(loc("uSandTex"), 2);
    glUniform1i(loc("uSandNormal"), 3);
    glUniform1i(loc("uGalaxy"), 4);
    auto bindTexture = [](int unit, GLuint tex) { glActiveTexture(GL_TEXTURE0 + unit); glBindTexture(GL_TEXTURE_2D, tex); };
    // Load first: loadTexture() binds to whichever unit is active, so it must not run between the binds below
    GLuint sandTex = loadTexture(ASSET_DIR "textures/sand_diff.jpg");
    GLuint sandNormal = loadTexture(ASSET_DIR "textures/sand_nor_gl.jpg");
    GLuint galaxyTex = loadTexture(ASSET_DIR "textures/galaxy.jpg");
    bindTexture(1, shadow.depthTex);
    bindTexture(2, sandTex);
    bindTexture(3, sandNormal);
    bindTexture(4, galaxyTex);
    glActiveTexture(GL_TEXTURE0);

    // ---------------- the scene ----------------
    World world;
    world.dust.init();
    world.build();
    Mesh* groundMesh = world.mesh(makeGrid(150.0f, 600));   // 0.5 m cells, shaped into liquid sand by the shader
    Mesh* skyMesh = world.mesh(makeSphere(1.0f, glm::vec3(0.0f), glm::vec3(1.0f), 1.0f, 16, 32));

    Settings set;
    const Joint joints[] = {
        {"camel spine", world.spine, 2}, {"camel neck", world.neck1, 2}, {"camel head", world.head, 2}, {"camel tail", world.tail, 0},
        {"camel front-left thigh", world.leg[0][0], 2}, {"camel front-left shin", world.leg[0][1], 2},
        {"camel back-right thigh", world.leg[3][0], 2}, {"camel back-right shin", world.leg[3][1], 2},
        {"explorer hips", world.hips, 0}, {"explorer chest", world.chest, 0}, {"explorer head", world.headE, 1},
        {"explorer left upper arm", world.upperArm[0], 0}, {"explorer left forearm", world.forearm[0], 0},
        {"explorer right thigh", world.thigh[1], 0}, {"explorer right shin", world.shin[1], 0}, {"floating rock ring", world.rockRing, 1},
    };
    const int NJOINTS = sizeof(joints) / sizeof(joints[0]);
    bool jointMode = false;
    int selJoint = 0;

    // Dynamic buffer for the skeleton overlay lines / points
    GLuint skelVao, skelVbo;
    glGenVertexArrays(1, &skelVao);
    glGenBuffers(1, &skelVbo);
    glBindVertexArray(skelVao);
    glBindBuffer(GL_ARRAY_BUFFER, skelVbo);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(glm::vec3), nullptr);
    glBindVertexArray(0);

    cam.pos = world.camelPos + glm::vec3(9.0f, 4.0f, -7.0f);
    cam.lookAt = world.camelPos + glm::vec3(0.0f, 1.5f, 0.0f);
    cam.setMode(CamMode::Free);

    // Per-frame values shared by the steps below
    float dt = 0.0f;                 // real seconds since the last frame
    int fbw = WIN_W, fbh = WIN_H;
    glm::mat4 view(1.0f), proj(1.0f);
    const glm::mat4 identity(1.0f);
    const glm::vec3 sunDir = glm::normalize(glm::vec3(-0.6f, 0.28f, 0.5f));   // low sunset sun
    const glm::vec3 sunColor(1.0f, 0.62f, 0.32f);

    // ===================================================================================================
    // Step: keyboard
    // ===================================================================================================
    bool keyWas[GLFW_KEY_LAST + 1] = {};
    auto pressed = [&](int k) {                   // true only on the frame the key goes down
        bool down = glfwGetKey(window, k) == GLFW_PRESS, edge = down && !keyWas[k];
        keyWas[k] = down;
        return edge;
    };
    auto handleInput = [&]() {
        if (glfwGetKey(window, GLFW_KEY_ESCAPE) == GLFW_PRESS) glfwSetWindowShouldClose(window, true);
        if (pressed(GLFW_KEY_1)) cam.setMode(CamMode::Follow);
        if (pressed(GLFW_KEY_2)) cam.setMode(CamMode::Side);
        if (pressed(GLFW_KEY_3)) cam.setMode(CamMode::Overview);
        if (pressed(GLFW_KEY_4)) cam.setMode(CamMode::Free);
        if (pressed(GLFW_KEY_5)) cam.setMode(CamMode::Rider);
        if (pressed(GLFW_KEY_SPACE)) set.paused = !set.paused;
        if (pressed(GLFW_KEY_EQUAL)) set.speed = std::min(set.speed * 1.5f, 8.0f);
        if (pressed(GLFW_KEY_MINUS)) set.speed = std::max(set.speed / 1.5f, 0.1f);
        if (pressed(GLFW_KEY_F1)) set.sun = !set.sun;
        if (pressed(GLFW_KEY_F2)) set.points = !set.points;
        if (pressed(GLFW_KEY_F3)) set.spec = !set.spec;
        if (pressed(GLFW_KEY_F4)) set.shading = (set.shading + 1) % 3;
        if (pressed(GLFW_KEY_F5)) set.spot = !set.spot;
        if (pressed(GLFW_KEY_F6)) set.textures = !set.textures;
        if (pressed(GLFW_KEY_F7)) set.normalMap = !set.normalMap;
        if (pressed(GLFW_KEY_F8)) set.shadows = !set.shadows;
        if (pressed(GLFW_KEY_V)) { set.wireframe = !set.wireframe; glPolygonMode(GL_FRONT_AND_BACK, set.wireframe ? GL_LINE : GL_FILL); }
        if (pressed(GLFW_KEY_H)) set.skeleton = !set.skeleton;
        if (pressed(GLFW_KEY_J)) jointMode = !jointMode;
        if (pressed(GLFW_KEY_TAB))
            selJoint = (selJoint + (glfwGetKey(window, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS ? NJOINTS - 1 : 1)) % NJOINTS;
        if (pressed(GLFW_KEY_R))
            for (const Joint& j : joints) j.node->extra = glm::vec3(0.0f);
        if (jointMode) {                         // arrow keys rotate the selected joint (held = continuous)
            Node* n = joints[selJoint].node;
            float r = 1.2f * dt;
            if (glfwGetKey(window, GLFW_KEY_UP) == GLFW_PRESS)    n->extra[joints[selJoint].axis] += r;
            if (glfwGetKey(window, GLFW_KEY_DOWN) == GLFW_PRESS)  n->extra[joints[selJoint].axis] -= r;
            if (glfwGetKey(window, GLFW_KEY_LEFT) == GLFW_PRESS)  n->extra.y += r;
            if (glfwGetKey(window, GLFW_KEY_RIGHT) == GLFW_PRESS) n->extra.y -= r;
        }
    };

    // ===================================================================================================
    // Step: camera
    // ===================================================================================================
    auto updateCamera = [&]() {
        if (cam.mode == CamMode::Rider) cam.attach(world.headE->frame());   // camera = child of the head node
        else cam.update(window, dt, world.camelPos + glm::vec3(0, 1.6f, 0), world.heading);
        if (cam.mode == CamMode::Free) {                       // walk over the dunes, never through them
            float ground = sandHeight(cam.pos.x, cam.pos.z, world.simTime) + 0.8f;
            if (cam.pos.y < ground) { cam.lookAt.y += ground - cam.pos.y; cam.pos.y = ground; }
        }
        glfwGetFramebufferSize(window, &fbw, &fbh);
        float aspect = fbh > 0 ? (float)fbw / (float)fbh : 1.0f;
        view = cam.view();
        proj = glm::perspective(glm::radians(cam.fov), aspect, 0.1f, 600.0f);
    };

    // ===================================================================================================
    // [Lighting: light sources (directional, point, spot)] sun, point lights and spotlight + per-frame uniforms
    // ===================================================================================================
    auto uploadFrameUniforms = [&]() {
        glUseProgram(program);
        glUniform3fv(loc("uCamPos"), 1, &cam.pos[0]);

        // Point lights: [0] = the lantern (it hangs from the explorer's hand, so it moves with the hierarchy),
        // then the (up to 3) ruins glowing the most while they form or crumble
        std::vector<glm::vec3> pointPos, pointColor;
        pointPos.push_back(glm::vec3(world.lantern->world * glm::vec4(LAMP_CORE, 1.0f)));
        pointColor.push_back(glm::vec3(0.5f, 1.05f, 1.4f));
        std::vector<const Ruin*> glowing;
        for (const Ruin& r : world.ruins) if (r.glow() > 0.05f) glowing.push_back(&r);
        std::sort(glowing.begin(), glowing.end(), [](const Ruin* a, const Ruin* b) { return a->glow() > b->glow(); });
        for (size_t i = 0; i < glowing.size() && pointPos.size() < 4; ++i) {
            const Ruin* r = glowing[i];
            glm::vec3 centre = (r->model->minB + r->model->maxB) * 0.5f;
            pointPos.push_back(glm::vec3(r->node->world * glm::vec4(centre, 1.0f)));
            pointColor.push_back(glm::vec3(1.0f, 0.45f, 0.12f) * 3.0f * r->glow());
        }
        // Spotlight: high above the camel and always aimed at it
        glm::vec3 spotPos = world.camelPos + glm::vec3(-6.0f, 28.0f, 5.0f);
        glm::vec3 spotDir = glm::normalize(world.camelPos - spotPos);
        glm::vec3 spotColor(0.95f, 0.72f, 0.38f);

        glUniform3fv(loc("uSunDir"), 1, &sunDir[0]);
        glUniform3fv(loc("uSunColor"), 1, &sunColor[0]);
        glUniform1i(loc("uNumPoints"), (int)pointPos.size());
        glUniform3fv(loc("uPointPos"), (GLsizei)pointPos.size(), &pointPos[0][0]);
        glUniform3fv(loc("uPointColor"), (GLsizei)pointColor.size(), &pointColor[0][0]);
        glUniform3fv(loc("uSpotPos"), 1, &spotPos[0]);
        glUniform3fv(loc("uSpotDir"), 1, &spotDir[0]);
        glUniform3fv(loc("uSpotColor"), 1, &spotColor[0]);
        glUniform1f(loc("uSpotInner"), std::cos(glm::radians(8.0f)));
        glUniform1f(loc("uSpotOuter"), std::cos(glm::radians(15.0f)));
        glUniform1i(loc("uUseSun"), set.sun);
        glUniform1i(loc("uUsePoint"), set.points);
        glUniform1i(loc("uUseSpot"), set.spot);
        glUniform1i(loc("uUseSpec"), set.spec);
        glUniform1i(loc("uShading"), set.shading);
        glUniform1i(loc("uUseTex"), set.textures);
        glUniform1i(loc("uUseNormalMap"), set.normalMap);
        glUniform1i(loc("uHighlight"), 0);
        glUniform1f(loc("uTime"), world.simTime);
        glUniform4fv(loc("uRipples"), MAX_RIPPLES, &world.ripples[0][0]);
        glm::mat3 skyRot = glm::mat3(glm::rotate(glm::mat4(1.0f), 1.2f, glm::vec3(1, 0, 0)) *            // Milky Way band overhead
                                     glm::rotate(glm::mat4(1.0f), 0.01f * world.simTime, glm::vec3(0, 1, 0)));   // slowly turning
        glUniformMatrix3fv(loc("uSkyRot"), 1, GL_FALSE, &skyRot[0][0]);
    };

    // All opaque objects that cast shadows. Drawn twice: into the shadow map and on screen.
    auto drawObjects = [&](const Node* selected) {
        glUniform1i(loc("uMode"), MODE_OBJECT);
        world.camelRoot->draw(program, selected);
        world.rockRing->draw(program, selected);
        world.lantern->draw(program);
        for (const Ruin& r : world.ruins) {
            if (r.presence <= 0.0f) continue;                   // completely turned to dust
            glUniform1f(loc("uDissolve"), 1.0f - r.presence);
            r.node->draw(program);
        }
        glUniform1f(loc("uDissolve"), 0.0f);
    };

    // ===================================================================================================
    // [Advanced: shadow mapping] PASS 1 - depth seen from the sun, centred on the camel
    // ===================================================================================================
    auto renderShadowPass = [&]() {
        glm::mat4 lightView = ShadowMap::lightView(sunDir, world.camelPos), lightProj = ShadowMap::lightProj();
        glm::mat4 lightSpace = lightProj * lightView;
        glUniformMatrix4fv(loc("uLightSpace"), 1, GL_FALSE, &lightSpace[0][0]);
        if (set.shadows) {
            shadow.begin();
            glUniform1i(loc("uShadowPass"), 1);
            glUniform1i(loc("uUseShadow"), 0);                // never read the map while writing it
            glUniformMatrix4fv(loc("uView"), 1, GL_FALSE, &lightView[0][0]);
            glUniformMatrix4fv(loc("uProj"), 1, GL_FALSE, &lightProj[0][0]);
            drawObjects(nullptr);
            glUniform1i(loc("uShadowPass"), 0);
            shadow.end(fbw, fbh);
        }
        glUniform1i(loc("uUseShadow"), set.shadows);
    };

    // ===================================================================================================
    // Step: PASS 2 - the scene from the camera
    // ===================================================================================================
    auto renderScenePass = [&]() {
        glClearColor(0.98f, 0.52f, 0.28f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glUniformMatrix4fv(loc("uView"), 1, GL_FALSE, &view[0][0]);
        glUniformMatrix4fv(loc("uProj"), 1, GL_FALSE, &proj[0][0]);

        // Sky: large sphere around the camera, no depth writes
        glUniform1i(loc("uMode"), MODE_SKY);
        glm::mat4 skyModel = glm::translate(identity, cam.pos) * glm::scale(identity, glm::vec3(400.0f));
        glUniformMatrix4fv(loc("uModel"), 1, GL_FALSE, &skyModel[0][0]);
        glDepthMask(GL_FALSE);
        drawMesh(*skyMesh, program);
        glDepthMask(GL_TRUE);

        // Sand: the grid follows the camera (snapped to whole 0.5 m cells so the waves do not slide),
        // so the desert never ends
        glUniform1i(loc("uMode"), MODE_SAND);
        glm::vec3 gridCentre(std::round(cam.pos.x * 2.0f) * 0.5f, 0.0f, std::round(cam.pos.z * 2.0f) * 0.5f);
        glm::mat4 groundModel = glm::translate(identity, gridCentre);
        glUniformMatrix4fv(loc("uModel"), 1, GL_FALSE, &groundModel[0][0]);
        drawMesh(*groundMesh, program);

        drawObjects(jointMode ? joints[selJoint].node : nullptr);

        // Transparent dust last: it is blended over everything already drawn
        world.dust.draw(dustProgram, view, proj, cam.pos, fbh);
        glUseProgram(program);
    };

    // Skeleton overlay (H): yellow lines parent -> child joint, red dots on the joints, drawn on top
    auto drawSkeletonOverlay = [&]() {
        if (!set.skeleton) return;
        std::vector<glm::vec3> lines, points;
        world.camelRoot->skeleton(lines, points);
        world.rockRing->skeleton(lines, points);
        std::vector<glm::vec3> all(lines);
        all.insert(all.end(), points.begin(), points.end());
        glBindBuffer(GL_ARRAY_BUFFER, skelVbo);
        glBufferData(GL_ARRAY_BUFFER, all.size() * sizeof(glm::vec3), all.data(), GL_STREAM_DRAW);
        glUniform1i(loc("uMode"), MODE_OVERLAY);
        glUniformMatrix4fv(loc("uModel"), 1, GL_FALSE, &identity[0][0]);
        glDisable(GL_DEPTH_TEST);
        glBindVertexArray(skelVao);
        glUniform4f(loc("uColor"), 1.0f, 0.9f, 0.2f, 1.0f);
        glLineWidth(2.0f);
        glDrawArrays(GL_LINES, 0, (GLsizei)lines.size());
        glUniform4f(loc("uColor"), 1.0f, 0.3f, 0.2f, 1.0f);
        glPointSize(7.0f);
        glDrawArrays(GL_POINTS, (GLint)lines.size(), (GLsizei)points.size());
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
    };

    auto updateTitle = [&]() {
        static const char* modes[] = {"", "Follow", "Side", "Overview", "Free roam (WASD)", "Rider"};
        static const char* shades[] = {"Phong", "Gouraud", "Flat"};
        char t[400];
        std::snprintf(t, sizeof t, "Desert of Liquid Sand | cam: %s | speed x%.1f%s | F1 sun:%d F2 points:%d F3 spec:%d "
                      "F4 %s F5 spot:%d F6 tex:%d F7 normal map:%d F8 shadow:%d%s%s",
                      modes[(int)cam.mode], set.speed, set.paused ? " (paused)" : "", set.sun, set.points, set.spec,
                      shades[set.shading], set.spot, set.textures, set.normalMap, set.shadows,
                      jointMode ? " | JOINT: " : "", jointMode ? joints[selJoint].name : "");
        glfwSetWindowTitle(window, t);
    };

    // ===================================================================================================
    // Main loop
    // ===================================================================================================
    double prev = glfwGetTime(), titleTimer = 0.0;
    while (!glfwWindowShouldClose(window)) {
        double now = glfwGetTime();
        dt = (float)(now - prev);
        prev = now;

        handleInput();
        world.update(set.paused ? 0.0f : dt * set.speed);
        updateCamera();
        uploadFrameUniforms();
        renderShadowPass();
        renderScenePass();
        drawSkeletonOverlay();

        glfwSwapBuffers(window);
        glfwPollEvents();

        if (now - titleTimer > 0.25) { titleTimer = now; updateTitle(); }   // the window title shows every switch
    }

    glDeleteProgram(program);
    glDeleteProgram(dustProgram);
    glfwTerminate();
    return 0;
}

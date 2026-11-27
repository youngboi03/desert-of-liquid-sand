#version 330 core
layout(location = 0) in vec4 aPosSize;   // xyz = world position, w = diameter (m)
layout(location = 1) in vec4 aColor;     // rgb + opacity

uniform mat4 uView;
uniform mat4 uProj;
uniform float uScreenH;                  // framebuffer height in pixels

out vec4 vColor;

void main() {
    gl_Position = uProj * uView * vec4(aPosSize.xyz, 1.0);
    // Perspective size: an object of size s at depth w covers s * proj[1][1] / w of the half screen height
    gl_PointSize = aPosSize.w * uProj[1][1] * 0.5 * uScreenH / gl_Position.w;
    vColor = aColor;
}

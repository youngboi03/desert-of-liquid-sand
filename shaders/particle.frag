#version 330 core
in vec4 vColor;
out vec4 FragColor;

void main() {
    // gl_PointCoord runs 0..1 across the point sprite: make a soft round grain instead of a square
    float r = length(gl_PointCoord - 0.5) * 2.0;
    if (r > 1.0) discard;
    float alpha = vColor.a * (1.0 - r * r);
    FragColor = vec4(vColor.rgb, alpha);
}

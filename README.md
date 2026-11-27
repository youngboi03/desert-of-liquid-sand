# Desert of Liquid Sand

CS7GV6 Computer Graphics, Project 1 (impossible world: Nature).

An explorer rides a camel along an endless trail through a desert of liquid sand. A lost city forms out of
the sand ahead of the camel and crumbles back into it behind, rocks float overhead, and the sky is a cracked
glass dome over the Milky Way. C++17, shader-based OpenGL 3.3 core profile.

**Demo video:** https://youtu.be/uwbIN8F0HKM

## Build and run

Needs CMake 3.16+ and a C++17 compiler. GLFW, GLM and Assimp are downloaded by CMake (FetchContent) on the
first configure; GLAD and stb_image are in `external/`.

```
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
./build/project1
```

Shader and asset paths are compiled in (`SHADER_DIR`, `ASSET_DIR`), so the program can run from any folder.

## Controls

| Key | Action |
|---|---|
| 1 / 2 / 3 / 4 / 5 | camera: follow, side, overview, free roam, rider's eyes |
| W A S D, Q / E, Shift | move (free roam), down / up, faster |
| mouse drag, wheel | look / orbit, speed or zoom |
| Space, - / = | pause, slower / faster |
| F1 / F2 / F5 | sun, point lights, spotlight |
| F3 | specular on / off |
| F4 | Phong / Gouraud / flat shading |
| F6 / F7 | textures, normal map |
| F8 | shadows |
| V | wireframe |
| H | skeleton overlay |
| J, Tab, arrows, R | joint mode: select a joint, rotate it, reset |
| Esc | quit |

The window title shows the state of every switch.

## Where each feature is

| Feature | Code |
|---|---|
| Light sources (directional sun, point lights, spotlight) | `src/main.cpp` uploadFrameUniforms(), `shaders/common.glsl` lightAt() |
| Blinn-Phong; Phong / Gouraud / flat shading | `shaders/common.glsl`, `shaders/scene.vert`, `shaders/scene.frag` |
| Texture loading, model UVs | `src/model.h` |
| Tiled sand texture, normal map, galaxy sky | `shaders/scene.frag` |
| Noise dissolve (ruins forming / crumbling) | `src/ruins.h`, `shaders/scene.frag` |
| Endless journey (ruin recycling) | `src/ruins.h` ahead() |
| Shadow mapping | `src/shadow.h`, `src/main.cpp` renderShadowPass(), `shaders/common.glsl` sunShadow() |
| Transparent dust particles | `src/particles.h`, `shaders/particle.*` |
| Liquid sand (moving dunes, footstep ripples) | `src/sand.h`, `shaders/scene.vert` |
| Skinning and scene graph | `src/node.h`, `src/model.h`, `src/world.h`, `shaders/scene.vert` |
| Secondary motion (cloak spring, lantern pendulum) | `src/spring.h`, `src/world.h` animateRider() |

`src/world.h` holds the scene layout and animation; `src/main.cpp` holds the window, input, cameras and
the two render passes. Feature blocks in the code are tagged with comments such as `// [Advanced: shadow mapping]`.

## Folders

| Folder | Contents |
|---|---|
| `src/`, `shaders/` | program source |
| `assets/models/` | `.glb` models loaded by the program (exported from Blender) |
| `assets/textures/` | sand colour and normal map, Milky Way panorama |
| `assets/source/*/license.txt` | source and licence of every downloaded asset |
| `blender/scripts/` | Blender Python scripts used to clean, split and texture the models and build the ruin kit |
| `external/` | GLAD loader and stb_image |

## Credits

**Sketchfab models (CC BY 4.0):** *camel* by omarme37; *Fremen of Dune* by count_zero; *Palmyra's Arch of
Triumph, Trafalgar Sq, London* by nebulousflynn; *Ancient ruins* by fedorzabelin; *Stylized sand stone pillar 2*
by BigAngrySkyGames; *Ancient Ruined Sandstone Archway & Gate* by mana5677; *Tempel von Edfu* by TRYFIELD;
*Egyptian Ruins* by local.yany; *Desert ruins #MedievalRemixChallenge* by Iso Game Lab; *Desert Ruins Set
Pieces* by Peter Andre; *Ancient Carved Stone Cliff 4* by mohamedhussien; *Colossus* by MASTER MODS; *Ancient
Ruins Pack* by Hawtor Studio. The models were cleaned, scaled and split with the scripts in `blender/scripts`;
the camel and the explorer were re-rigged and weight-painted for this project.

**Poly Haven (CC0):** Lantern 01, Namaqualand Boulder 04, Lion Head, Bull Head, Marble Bust 01, Concrete Cat
Statue, Antique Ceramic Vase 01, Namaqualand Cliff 01 and 02, Namaqualand Boulders 01, Namaqualand Boulder 02,
05 and 06, Rock 07, Rock 09, Quiver Tree 01, Dead Quiver Trunk, Dead Tree Trunk 02; textures Aerial Beach 01,
Large Sandstone Blocks, Large Sandstone Blocks 01, Old Sandstone 02, Rabdentse Ruins Wall, Sandstone Cracks.

**Sky:** *The Milky Way panorama* (eso0932a), ESO/S. Brunier, CC BY 4.0.

**Libraries:** GLFW, GLAD, GLM, Assimp, stb_image.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const palettes = {
  silver: { color: '#b8bbc0', metalness: 0.35, roughness: 0.35, background: '#191b1e' },
  blue: { color: '#249ddd', metalness: 0.15, roughness: 0.40, background: '#19232e' },
  graphite: { color: '#555d68', metalness: 0.65, roughness: 0.28, background: '#191b1e' },
  gold: { color: '#ce9d51', metalness: 0.80, roughness: 0.30, background: '#211e19' },
  violet: { color: '#9270cf', metalness: 0.25, roughness: 0.38, background: '#201d28' },
};

// Shared camera, material and studio lighting for the live model and docs
// frames. The reference orientation is stored in the GLB itself.
export async function createStage(canvas, palette = 'blue') {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  const room = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(room, 0.04);
  scene.environment = environment.texture;
  room.dispose();
  pmrem.dispose();
  scene.add(new THREE.HemisphereLight('#ffffff', '#202020', 0.15));
  for (const [intensity, position] of [[4.5, [-5, 6, 2]], [0.15, [4, 0, 2]], [2.5, [1, 3, -5]]]) {
    const light = new THREE.DirectionalLight('#ffffff', intensity);
    light.position.set(...position);
    scene.add(light);
  }
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  camera.position.set(0, 0, 10);
  camera.lookAt(0, 0, 0);
  let gltf;
  try {
    gltf = await new GLTFLoader().loadAsync('/icon/icon.glb');
  } catch (error) {
    environment.dispose();
    renderer.dispose();
    throw error;
  }
  scene.add(gltf.scene);
  const clip = gltf.animations.find(clip => clip.name === 'UnisonGrowth');
  const meshes = [];
  gltf.scene.traverse(object => { if (object.isMesh) meshes.push(object); });
  function dispose() {
    renderer.setAnimationLoop(null);
    const materials = new Set(meshes.map(mesh => mesh.material));
    for (const mesh of meshes) mesh.geometry.dispose();
    for (const material of materials) material.dispose();
    environment.dispose();
    renderer.dispose();
  }
  if (!clip || gltf.animations.length !== 1) {
    dispose();
    throw new Error('Regenerate icon.glb with its unison animation.');
  }
  const mixer = new THREE.AnimationMixer(gltf.scene);
  const action = mixer.clipAction(clip).play();
  function setPalette(name) {
    const selected = palettes[name];
    if (!selected) throw new Error(`Unknown palette: ${name}`);
    scene.environmentIntensity = name === 'silver' ? 0.15 : 0.55;
    for (const mesh of meshes) {
      mesh.material.color.set(selected.color);
      mesh.material.metalness = selected.metalness;
      mesh.material.roughness = selected.roughness;
    }
  }
  setPalette(palette);
  return {
    renderer, scene, camera, mixer, action, setPalette,
    renderAt(seconds) { mixer.setTime(seconds); renderer.render(scene, camera); },
    dispose() {
      mixer.stopAllAction();
      mixer.uncacheRoot(gltf.scene);
      dispose();
    },
  };
}

import * as THREE from 'three';

// An icosahedral hub with twenty swept triangular prongs. Viewed along a
// vertex, five foreground prongs meet at the center, as in the reference.
const PHI = (1 + Math.sqrt(5)) / 2;
const directions = [];
for (const a of [-1, 1]) for (const b of [-PHI, PHI]) {
  directions.push(new THREE.Vector3(0, a, b).normalize());
  directions.push(new THREE.Vector3(a, b, 0).normalize());
  directions.push(new THREE.Vector3(b, 0, a).normalize());
}
const edge = Math.min(...directions.slice(1).map(point => directions[0].distanceTo(point)));
const faces = [];
for (let a = 0; a < 12; a++) for (let b = a + 1; b < 12; b++) {
  for (let c = b + 1; c < 12; c++) {
    if ([[a, b], [b, c], [c, a]].every(([i, j]) =>
      Math.abs(directions[i].distanceTo(directions[j]) - edge) < 1e-6)) {
      faces.push([a, b, c].map(index => directions[index].clone().multiplyScalar(0.94)));
    }
  }
}

function faceFor(index) {
  const points = faces[index];
  const center = points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).multiplyScalar(1 / 3);
  const normal = center.clone().normalize();
  // A shared azimuth makes the curl flow consistently around the logo's axis.
  const axis = directions[11];
  const u = new THREE.Vector3().crossVectors(axis, normal).normalize();
  const v = new THREE.Vector3().crossVectors(normal, u);
  points.sort((a, b) => Math.atan2(a.dot(v), a.dot(u)) - Math.atan2(b.dot(v), b.dot(u)));
  return { normal, u, v, center, points };
}

function geometryFromTriangles(triangles) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(triangles.flatMap(
    triangle => triangle.flatMap(p => p.toArray()),
  ), 3));
  geometry.computeVertexNormals();
  return geometry;
}

// Calibrated long endpoint for the default mark.
const LONG_EXTENSION = 0.80 * (1 - Math.cos(2 * Math.PI * 0.35)) / 2;
const RETRACTION = 1.25;

function prongGeometry(face, retraction) {
  const { normal, u, v, center, points } = face;
  // The crown translates rigidly, while the trunk always starts at the
  // exact shared hub face. Fixing that full perimeter prevents the tapered
  // prongs from sliding through the hub and exposing seams when retracted.
  const rings = [
    { height: -0.025, width: 1, twist: 0 },
    { height: 0, width: 1, twist: 0 },
    { height: 1.35, width: 0.60, twist: 0.10 },
    { height: 1.55, width: 0.45, twist: 0.14 },
  ].map(({ height, width, twist }, ring) => points.map(point => {
    // Reuse the hub coordinates directly, including at adjacent prongs;
    // no basis reconstruction, scale padding, or approximate attachment.
    if (ring < 2) return point.clone().addScaledVector(normal, height);
    const local = point.clone().sub(center);
    const angle = twist;
    const x = local.dot(u) * width;
    const y = local.dot(v) * width;
    const curl = 0.13 * (height / 1.5) ** 2;
    return center.clone()
      .addScaledVector(normal, height + LONG_EXTENSION - retraction * RETRACTION)
      .addScaledVector(u, x * Math.cos(angle) - y * Math.sin(angle) + curl)
      .addScaledVector(v, x * Math.sin(angle) + y * Math.cos(angle));
  }));
  const triangles = [];
  for (let r = 0; r < rings.length - 1; r++) for (let i = 0; i < 3; i++) {
    const j = (i + 1) % 3;
    triangles.push([rings[r][i], rings[r][j], rings[r + 1][j]]);
    triangles.push([rings[r][i], rings[r + 1][j], rings[r + 1][i]]);
  }
  for (let i = 1; i < 2; i++) {
    triangles.push([rings[0][0], rings[0][i + 1], rings[0][i]]);
    triangles.push([rings[3][0], rings[3][i], rings[3][i + 1]]);
  }
  return geometryFromTriangles(triangles);
}

export function createIcon() {
  const group = new THREE.Group();
  group.name = 'Icon';
  const material = new THREE.MeshStandardMaterial({
    color: '#249ddd', metalness: 0.15, roughness: 0.40, flatShading: true,
  });
  const hubTriangles = [];
  const prongs = faces.map((_, i) => {
    const face = faceFor(i);
    for (let j = 1; j < 2; j++) hubTriangles.push([face.points[0], face.points[j], face.points[j + 1]]);
    const geometry = prongGeometry(face, 0);
    const shortened = prongGeometry(face, 1);
    geometry.morphAttributes.position = [shortened.getAttribute('position').clone()];
    geometry.morphAttributes.normal = [shortened.getAttribute('normal').clone()];
    shortened.dispose();
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = `Prong_${String(i + 1).padStart(2, '0')}`;
    mesh.morphTargetDictionary = { RetractTrunk: 0 };
    group.add(mesh);
    return mesh;
  });
  const hub = new THREE.Mesh(geometryFromTriangles(hubTriangles), material);
  hub.name = 'Core';
  group.add(hub);
  // Store the reference orientation in the asset itself.
  group.quaternion.setFromUnitVectors(directions[11], new THREE.Vector3(0, 0, 1));
  group.rotateZ(-0.10);
  group.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -0.68));
  return { group, prongs };
}

export const LOOP_SECONDS = 8;
export const ORBIT_SECONDS = LOOP_SECONDS * 10;
export function expansionAt(seconds) {
  // Each prong moves for its entire cycle, easing through instantaneous
  // direction reversals without a hold at either end. The cycle carries
  // through the orbit loop seam without a pause.
  const local = ((seconds % LOOP_SECONDS) + LOOP_SECONDS) % LOOP_SECONDS;
  return (1 - Math.cos(2 * Math.PI * local / LOOP_SECONDS)) / 2;
}

export function createGrowthClip(prongs, group) {
  const times = Array.from({ length: 2401 }, (_, i) => i * ORBIT_SECONDS / 2400);
  const tracks = prongs.map(prong =>
    new THREE.NumberKeyframeTrack(`${prong.name}.morphTargetInfluences`, times,
      times.map(time => expansionAt(time))),
  );
  // Orbit the actual model around world-up, preserving the reference pose
  // at both ends. The exported clip includes all ten contraction cycles.
  const orbitTimes = Array.from({ length: 121 }, (_, i) => i * ORBIT_SECONDS / 120);
  const rotations = orbitTimes.flatMap(time => new THREE.Quaternion()
    .setFromAxisAngle(new THREE.Vector3(0, 1, 0), 2 * Math.PI * time / ORBIT_SECONDS)
    .multiply(group.quaternion).toArray());
  tracks.push(new THREE.QuaternionKeyframeTrack(`${group.name}.quaternion`, orbitTimes, rotations));
  return new THREE.AnimationClip('UnisonGrowth', ORBIT_SECONDS, tracks);
}

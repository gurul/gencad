import { mkdir, writeFile } from 'node:fs/promises';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { createIcon, createGrowthClip } from '../../src/lib/icon/model.mjs';

// The texture-free exporter only needs FileReader's ArrayBuffer operation.
globalThis.FileReader = class {
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then(result => { this.result = result; this.onloadend?.(); })
      .catch(error => this.onerror?.(error));
  }
};
const { group, prongs } = createIcon();
const glb = await new GLTFExporter().parseAsync(group, {
  binary: true,
  animations: [createGrowthClip(prongs, group)],
});
const directory = new URL('../../public/icon/', import.meta.url);
await mkdir(directory, { recursive: true });
await writeFile(new URL('icon.glb', directory), Buffer.from(glb));
console.log(`Wrote public/icon/icon.glb (${glb.byteLength.toLocaleString()} bytes, 20 growing trunks, unison clip).`);

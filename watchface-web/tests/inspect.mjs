/**
 * 结构检查：把 .face 拆开，打印头部关键字段、索引/描述块、以及 main.lua 里的分页信息。
 *
 *   node tests/inspect.mjs <a.face> [b.face ...]
 */
import { readFileSync } from 'node:fs';
import { unpackFace } from '../src/core/facebin.js';

for (const p of process.argv.slice(2)) {
  const raw = new Uint8Array(readFileSync(p));
  const u = unpackFace(raw);
  const frames = u.files.filter((f) => /^lua\/face_/.test(f.name));
  const lua = u.files.find((f) => /main\.lua$/.test(f.name));
  console.log(`\n== ${p.split(/[\\/]/).pop()}  ${raw.length} B`);
  console.log(`   title="${u.title}" id="${u.faceId}" idLen=${u.idLen} screens=${u.screens} hasAod=${u.hasAod}`);
  console.log(`   n=${u.n} frames=${frames.length} idx=${u.idx} d0=${u.d0} descEnd=${u.descEnd} assetsEnd=${u.assetsEnd}`);
  console.log(`   recs=${u.recs.length} ${JSON.stringify(u.recs.map((r) => '0x' + r.tag.toString(16)))}`);
  console.log(`   preview=${u.preview.w}x${u.preview.h} bytes=${u.preview.len}`);
  if (lua) {
    const txt = new TextDecoder().decode(lua.data);
    const lines = txt.split('\n').filter((l) => /count|PAGES|page|fps|period/i.test(l));
    console.log('   lua:', lines.slice(0, 10).map((l) => l.trim()).join(' ⏎ '));
  }
}

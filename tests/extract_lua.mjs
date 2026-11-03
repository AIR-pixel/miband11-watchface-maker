// 把 .face 里的 main.lua 吐出来，供 luaparser 语法检查
import { readFileSync, writeFileSync } from 'node:fs';
import { unpackFace } from '../src/core/facebin.js';
const src = new Uint8Array(readFileSync(process.argv[2]));
const u = unpackFace(src);
const lua = u.files.find((f) => /main\.lua$/.test(f.name));
writeFileSync(process.argv[3] || 'main.lua', lua.data);
console.log('wrote', process.argv[3], lua.data.length, 'bytes');

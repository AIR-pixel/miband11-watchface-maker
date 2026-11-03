/**
 * 调色板 PNG 编码器（color type 3，8 位索引）。
 *
 * 浏览器与 Node 都没有同步 zlib，所以用 CompressionStream('deflate') 拿
 * zlib（RFC1950）流 —— 这正好是 PNG IDAT 要的格式。因此 encodePNG 是 async。
 */

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes, start = 0, end = bytes.length) {
  let c = 0xffffffff;
  for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function u32be(v) {
  return new Uint8Array([(v >>> 24) & 0xff, (v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff]);
}

function chunk(type, data) {
  const typeBytes = new Uint8Array([...type].map((ch) => ch.charCodeAt(0)));
  const body = new Uint8Array(typeBytes.length + data.length);
  body.set(typeBytes, 0);
  body.set(data, typeBytes.length);
  const out = new Uint8Array(4 + body.length + 4); // 4 长度 + (4 类型 + 数据) + 4 CRC
  out.set(u32be(data.length), 0);
  out.set(body, 4);
  const c = crc32(body);
  out.set(u32be(c), 4 + body.length);
  return out;
}

async function deflateZlib(bytes) {
  const cs = new CompressionStream('deflate');
  const stream = new Blob([bytes]).stream().pipeThrough(cs);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/**
 * @param {Uint8Array} indices 每像素一个调色板下标，长度 = w*h
 * @param {Uint8Array} palette RGB 三元组，最多 256 色
 * @param {number} w
 * @param {number} h
 * @param {number} level 压缩级别（只影响速度，不影响正确性）
 * @returns {Promise<Uint8Array>}
 */
export async function encodePNG(indices, palette, w, h) {
  const nColors = palette.length / 3;
  if (nColors > 256) throw new Error('调色板超过 256 色');

  const ihdr = new Uint8Array(13);
  ihdr.set(u32be(w), 0);
  ihdr.set(u32be(h), 4);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 3;  // palette
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  // 过滤类型 0（None）。调色板图用 Sub/Up 收益很小，省一次全图扫描。
  const raw = new Uint8Array((w + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w + 1)] = 0;
    raw.set(indices.subarray(y * w, y * w + w), y * (w + 1) + 1);
  }
  const idat = await deflateZlib(raw);

  const parts = [
    new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('PLTE', palette.subarray(0, nColors * 3)),
    chunk('IDAT', idat),
    chunk('IEND', new Uint8Array(0)),
  ];
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

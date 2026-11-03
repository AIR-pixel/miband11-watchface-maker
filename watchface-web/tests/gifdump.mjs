import { readFileSync } from 'node:fs';
const b = new Uint8Array(readFileSync(process.argv[2]));
console.log('sig', String.fromCharCode(...b.subarray(0,6)));
console.log('w,h', b[6]|(b[7]<<8), b[8]|(b[9]<<8), 'packed', b[10].toString(2), 'bg', b[11], 'aspect', b[12]);
let p = 13;
if (b[10] & 0x80) p += (2 << (b[10] & 7)) * 3;
console.log('first block @', p, '0x' + b[p].toString(16));
let count=0;
while (p < b.length && count < 4) {
  const blk = b[p];
  if (blk === 0x3b) { console.log('trailer @', p); break; }
  if (blk === 0x21) { console.log('ext @', p, 'label 0x'+b[p+1].toString(16)); p += 2; while (b[p] !== 0) p += b[p] + 1; p += 1; }
  else if (blk === 0x2c) { console.log('image @', p, 'w,h', b[p+5]|(b[p+6]<<8), b[p+7]|(b[p+8]<<8), 'packed', b[p+9].toString(2)); break; }
  else { console.log('unknown @', p); break; }
  count++;
}

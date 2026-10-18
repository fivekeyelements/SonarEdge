const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/web/app.js', 'utf8');
const start = source.indexOf('function fit() {');
const end = source.indexOf("window.addEventListener('resize'", start);
assert.ok(start >= 0 && end > start);
const fit = source.slice(start, end);
for (const [width,height] of [[2536,696],[2560,720],[1600,481],[2558,718],[1688,696]]) {
  const stage = {style:{}};
  vm.runInNewContext(fit + ';fit();', {
    $: () => stage, innerWidth:width, innerHeight:height,
    URLSearchParams, location:{search:'?icue=xl'},
  });
  const logicalWidth = parseFloat(stage.style.width);
  const scale = Number(stage.style.transform.match(/scale\(([^)]+)\)/)[1]);
  assert.ok(Math.abs(logicalWidth * scale - width) < 1e-6, `Width must fill ${width}x${height}`);
  if(width/height>2.5) assert.ok(Math.abs(720 * scale - height) < 1e-6, `Height must fill ${width}x${height}`);
  else assert.ok(720 * scale <= height, 'Narrow slots must preserve the panel aspect ratio');
}
console.log('Desktop and XL widget fill wide viewports without letterbox borders; smaller slots retain aspect ratio.');

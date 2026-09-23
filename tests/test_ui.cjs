// Run with Node locally; audit also ran this using Kibana's bundled Node runtime.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = globalThis.APP_SOURCE ?? require('node:fs').readFileSync('app/static/app.js', 'utf8');
const elements = new Map();
const bad = '<img src=x onerror=alert(1)> & "quoted"';
const products = [{id: 1, name: bad, variant: bad, price: 1, available_quantity: 2, reserved_quantity: 0, sold_quantity: 0}];
const orders = [{id: 1, customer_reference: bad, items: [{product_name: bad, quantity: 1}], total: 1, status: 'PENDING'}];
const context = {
  document: {
    querySelector: (selector) => { if (!elements.has(selector)) elements.set(selector, {}); return elements.get(selector); },
    querySelectorAll: () => []
  },
  fetch: async (url) => ({ok: true, json: async () => url === '/api/products' ? products : orders}),
  console
};
vm.createContext(context);
vm.runInContext(source, context);
(async () => {
  await context.refresh();
  for (const selector of ['#product-select', '#products', '#orders']) {
    const rendered = elements.get(selector).innerHTML;
    assert(!rendered.includes('<img'), selector);
    assert(rendered.includes('&lt;img'), selector);
    assert(rendered.includes('&amp;'), selector);
  }
  assert(elements.get('#orders').innerHTML.includes('PACKED'));
  console.log('PASS: untrusted display text escaped in product selector, inventory and orders; order controls retained');
})().catch((error) => { console.error(error); process.exitCode = 1; });

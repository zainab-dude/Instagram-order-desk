const message = document.querySelector('#message');
const productSelect = document.querySelector('#product-select');

// User-entered names/references must render as text, never executable HTML.
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || 'Request failed');
  return body;
}

function showMessage(text) { message.textContent = text; }

async function refresh() {
  const [products, orders] = await Promise.all([request('/api/products'), request('/api/orders')]);
  
  productSelect.innerHTML = products.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}${p.variant ? ` - ${escapeHtml(p.variant)}` : ''} (${p.available_quantity} available)</option>`).join('');
  
  document.querySelector('#products').innerHTML = products.length 
    ? products.map((p) => `
        <div class="row">
          <span>
            <strong>${escapeHtml(p.name)}</strong> ${p.variant ? `(${escapeHtml(p.variant)})` : ''}<br>
            <span class="muted">$${p.price.toFixed(2)} | ${p.available_quantity} available | ${p.reserved_quantity} reserved | ${p.sold_quantity} sold</span>
          </span>
          <button class="secondary stock-button" data-id="${p.id}">Update stock</button>
        </div>
      `).join('') 
    : '<p class="muted">No products yet.</p>';

  document.querySelector('#orders').innerHTML = orders.length 
    ? orders.map((o) => `
        <div class="row">
          <span>
            <strong>#${o.id} ${escapeHtml(o.customer_reference)}</strong><br>
            <span class="muted">${o.items.map((i) => `${escapeHtml(i.product_name)} x${i.quantity}`).join(', ')} | $${o.total.toFixed(2)}</span>
          </span>
          <span><strong>${o.status}</strong>${nextActions(o)}</span>
        </div>
      `).join('') 
    : '<p class="muted">No orders yet.</p>';

  document.querySelectorAll('.stock-button').forEach((button) => button.onclick = () => updateStock(button.dataset.id));
  document.querySelectorAll('.status-button').forEach((button) => button.onclick = () => updateStatus(button.dataset.id, button.dataset.status));
}

function nextActions(order) {
  const next = { PENDING: 'PACKED', PACKED: 'SHIPPED', SHIPPED: 'COMPLETED' }[order.status];
  if (!next) return '';
  return `<button class="secondary status-button" data-id="${order.id}" data-status="${next}">${next}</button><button class="secondary status-button" data-id="${order.id}" data-status="CANCELLED">Cancel</button>`;
}

async function updateStock(id) { 
  const value = prompt('New total stock quantity:'); 
  if (value === null) return; 
  try { 
    await request(`/api/products/${id}/stock`, { method: 'PATCH', body: JSON.stringify({ stock_quantity: Number(value) }) }); 
    showMessage('Stock updated.'); 
    await refresh(); 
  } catch (error) { 
    showMessage(error.message); 
  } 
}

async function updateStatus(id, status) { 
  try { 
    await request(`/api/orders/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }); 
    showMessage(`Order moved to ${status}.`); 
    await refresh(); 
  } catch (error) { 
    showMessage(error.message); 
  } 
}

document.querySelector('#product-form').onsubmit = async (event) => { 
  event.preventDefault(); 
  const form = new FormData(event.target); 
  try { 
    await request('/api/products', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) }); 
    event.target.reset(); 
    showMessage('Product added.'); 
    await refresh(); 
  } catch (error) { 
    showMessage(error.message); 
  } 
};

document.querySelector('#order-form').onsubmit = async (event) => { 
  event.preventDefault(); 
  const form = new FormData(event.target); 
  try { 
    await request('/api/orders', { 
      method: 'POST', 
      body: JSON.stringify({ 
        customer_reference: form.get('customer_reference'), 
        items: [{ product_id: Number(form.get('product_id')), quantity: Number(form.get('quantity')) }] 
      }) 
    }); 
    event.target.reset(); 
    showMessage('Order created and stock reserved.'); 
    await refresh(); 
  } catch (error) { 
    showMessage(error.message); 
  } 
};

document.querySelector('#refresh').onclick = () => refresh().catch((error) => showMessage(error.message));
refresh().catch((error) => showMessage(error.message));

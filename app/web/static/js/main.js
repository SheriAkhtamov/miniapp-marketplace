// tg уже объявлен глобально в <head> (window.tg = Telegram.WebApp)
// Здесь только локальный алиас для удобства
if (!window.tg) window.tg = window.Telegram.WebApp;
const tg = window.tg;

// Telegram BackButton для навигации
function initBackButton() {
    const path = window.location.pathname;

    // Если мы НЕ на главной странице магазина
    if (path !== '/shop' && path !== '/shop/') {
        tg.BackButton.show();
        tg.BackButton.onClick(() => {
            window.history.back();
        });
    } else {
        tg.BackButton.hide();
    }
}

// Вызываем при загрузке DOM
document.addEventListener('DOMContentLoaded', initBackButton);

// Global Spring Toast
function showToast(message, type = 'success') {
    // Remove existing
    const existing = document.getElementById('custom-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'custom-toast';
    // Spring animation class + aesthetics
    toast.className = `fixed top-6 left-1/2 transform -translate-x-1/2 bg-white text-[#3E2310] px-5 py-3 rounded-2xl shadow-xl z-[100] flex items-center space-x-3 !max-w-[90%] border border-[#F2E8DC] transition-all duration-500 ease-[cubic-bezier(0.68,-0.55,0.27,1.55)] opacity-0 translate-y-[-20px]`;

    // Icon based on type
    let icon = '✅';
    if (type === 'error') icon = '🛑';
    if (type === 'info') icon = 'ℹ️';

    toast.innerHTML = `
        <span class="text-lg">${icon}</span>
        <span class="text-sm font-bold tracking-wide">${message}</span>
    `;

    document.body.appendChild(toast);

    // Trigger animation
    setTimeout(() => {
        toast.classList.remove('opacity-0', 'translate-y-[-20px]');
    }, 50);

    // Haptic
    if (type === 'success') tg.HapticFeedback.notificationOccurred('success');
    else if (type === 'error') tg.HapticFeedback.notificationOccurred('error');

    // Remove
    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-[-20px]');
        setTimeout(() => toast.remove(), 500);
    }, 2500);
}

// Global Video Player for product modal
function playModalVideo(btn) {
    const wrap = btn.closest('[data-video-wrap]');
    if (!wrap) return;
    const video = wrap.querySelector('video');
    if (!video) return;

    if (video.paused) {
        // Pause all other videos in carousel
        document.querySelectorAll('[data-video-wrap] video').forEach(v => {
            if (v !== video && !v.paused) v.pause();
        });
        video.play();
        btn.style.opacity = '0';
        btn.style.pointerEvents = 'none';
        // Show play button again when video ends or is paused
        const showBtn = () => {
            btn.style.opacity = '1';
            btn.style.pointerEvents = '';
            // Change icon to replay if ended
            const icon = btn.querySelector('i');
            if (icon && video.ended) {
                icon.className = 'fas fa-redo text-[#3E2310] text-xl';
            } else if (icon) {
                icon.className = 'fas fa-play text-[#3E2310] text-xl ml-1';
            }
        };
        video.onpause = showBtn;
        video.onended = showBtn;
        // Tap video itself to pause
        video.onclick = () => { if (!video.paused) video.pause(); };
    } else {
        video.pause();
    }
}

// Global Cart Badge Update
function updateCartBadge(count) {
    const badge = document.getElementById('cart-badge');
    if (!badge) return;

    if (count > 0) {
        badge.innerText = count;
        badge.classList.remove('hidden');
        // Pop animation
        badge.classList.add('scale-125');
        setTimeout(() => badge.classList.remove('scale-125'), 200);
    } else {
        badge.classList.add('hidden');
    }
}

async function addToCart(productId) {
    tg.HapticFeedback.impactOccurred('medium');

    // Optimistic UI could be here, but for now standard fetch
    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
        const response = await fetch(`/shop/api/cart/add/${productId}`, {
            method: 'POST',
            headers: {
                'X-CSRF-Token': csrfToken
            }
        });
        const result = await response.json();

        if (result.success) {
            showToast(T.added_to_cart);
            updateCartBadge(result.total_count);
        } else {
            showToast(result.message || T.error, 'error');
        }
    } catch (e) {
        showToast(T.connection_error, 'error');
    }
}

// --- Shared product feed state for catalog/search pages ---
let _filterState = { query: '', categoryId: 'all', page: 1, hasMore: true, loading: false };

async function filterByCategory(catId) {
    tg.HapticFeedback.selectionChanged();
    _filterState.categoryId = catId;
    _filterState.page = 1;
    _filterState.hasMore = true;

    const buttons = document.querySelectorAll('#categories button');
    buttons.forEach(btn => {
        if (btn.getAttribute('data-id') === String(catId)) {
            btn.className = "chip-button active flex-shrink-0";
        } else {
            btn.className = "chip-button flex-shrink-0";
        }
    });

    await _loadProducts(true);
}

async function _loadProducts(replace = false) {
    if (_filterState.loading) return;
    if (!replace && !_filterState.hasMore) return;

    const container = document.getElementById('products-grid');
    if (!container) return;

    _filterState.loading = true;
    if (replace) container.classList.add('opacity-50');

    try {
        const params = new URLSearchParams({
            q: _filterState.query,
            category_id: _filterState.categoryId,
            page: _filterState.page,
            limit: 20,
        });
        const response = await fetch(`/shop/api/products/filter?${params}`);
        const data = await response.json();

        if (replace) {
            container.innerHTML = data.html;
        } else {
            container.insertAdjacentHTML('beforeend', data.html);
        }

        _filterState.hasMore = data.has_more;
        _filterState.page++;
    } catch (e) {
        if (replace) showToast(T.search_error, 'error');
    } finally {
        _filterState.loading = false;
        container.classList.remove('opacity-50');
    }
}

// Infinite scroll observer
function _initInfiniteScroll() {
    const sentinel = document.getElementById('scroll-sentinel');
    if (!sentinel) return;

    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && _filterState.hasMore && !_filterState.loading) {
            _loadProducts(false);
        }
    }, { rootMargin: '200px' });

    observer.observe(sentinel);
}

async function toggleFavorite(btn, productId) {
    tg.HapticFeedback.impactOccurred('light');
    const icon = btn.querySelector('i');

    if (icon.classList.contains('far')) {
        icon.classList.replace('far', 'fas');
        icon.classList.add('text-[#A33B20]');
        showToast(T.in_favorites, 'info');
    } else {
        icon.classList.replace('fas', 'far');
        icon.classList.remove('text-[#A33B20]');
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    await fetch(`/shop/api/favorite/${productId}`, {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken }
    });
}

// Opens the regular bot chat, where the bot asks for a contact using Telegram's
// native request_contact keyboard. The URL is generated server-side so the bot
// username remains a deployment setting rather than a hard-coded client value.
function openPhoneRequestBot() {
    const botUrl = document.body?.dataset.phoneRequestUrl;
    if (!botUrl) {
        showToast(T.phone_request_unavailable || T.error, 'error');
        return;
    }

    try {
        tg.HapticFeedback.impactOccurred('medium');
        if (typeof tg.openTelegramLink === 'function') {
            tg.openTelegramLink(botUrl);
            return;
        }
    } catch (error) {
        console.warn('Unable to open the bot from Mini App', error);
    }

    window.location.assign(botUrl);
}

function _money(n) {
    return Number(n || 0).toLocaleString('ru-RU') + ' ' + T.sum;
}

function hasProductDiscount(price, discountPrice) {
    price = Number(price) || 0;
    discountPrice = Number(discountPrice) || 0;
    return discountPrice > 0 && price > 0 && discountPrice < price;
}

function productPriceMarkup(price, discountPrice, mode) {
    const hasDiscount = hasProductDiscount(price, discountPrice);
    const current = hasDiscount ? discountPrice : price;
    const currentClass = mode === 'modal'
        ? 'product-price__current product-price__current--modal'
        : 'product-price__current';
    const regularClass = hasDiscount ? '' : ' product-price__current--regular';

    if (!hasDiscount) {
        return `<span class="${currentClass}${regularClass}">${_money(current)}</span>`;
    }

    return `
        <span class="${currentClass}">${_money(current)}</span>
        <span class="product-price__old">${_money(price)}</span>
    `;
}

// Cart Page Functions
// Debounce storage
const cartDebounceTimers = {};

async function updateCartQuantity(cartId, change) {
    tg.HapticFeedback.selectionChanged();
    const qtyElem = document.getElementById(`qty-${cartId}`);
    const maxStock = parseInt(qtyElem.dataset.stock) || 999999;
    const minQty = parseInt(qtyElem.dataset.minQuantity) || 1;
    // Get current value from DOM
    let currentQty = parseInt(qtyElem.value) || minQty;
    let newQty = currentQty + change;

    if (newQty < minQty) return;
    if (newQty > maxStock) {
        newQty = maxStock;
        if (newQty === currentQty) return;
    }

    // Optimistic UI Update
    qtyElem.value = newQty;
    calculateTotal();

    // Block checkout IMMEDIATELY (before debounce fires)
    if (!cartDebounceTimers[cartId]) {
        activeRequests++;
    }
    updateCheckoutButtonState();

    // Clear previous timer for this item
    if (cartDebounceTimers[cartId]) {
        clearTimeout(cartDebounceTimers[cartId]);
    }

    // Set new timer
    cartDebounceTimers[cartId] = setTimeout(async () => {
        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            const response = await fetch(`/shop/api/cart/update/${cartId}?qty=${newQty}`, {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrfToken }
            });
            const result = await response.json();
            if (result.success === false) {
                qtyElem.value = currentQty;
                showToast(result.message || T.update_error, 'error');
            }
            delete cartDebounceTimers[cartId];
        } catch (e) {
            // Revert on error (not perfect but safe)
            qtyElem.value = currentQty;
            showToast(T.update_error, 'error');
        } finally {
            activeRequests--;
            updateCheckoutButtonState();
        }
    }, 500);
}

function handleCartQtyInput(input) {
    // Strip non-digit characters
    input.value = input.value.replace(/[^0-9]/g, '');
    calculateTotal();
}

function commitCartQtyInput(input) {
    const cartId = input.dataset.cartId;
    const maxStock = parseInt(input.dataset.stock) || 999999;
    const minQty = parseInt(input.dataset.minQuantity) || 1;
    let val = parseInt(input.value);

    // Clamp to valid range
    if (!val || val < minQty) val = minQty;
    if (val > maxStock) val = maxStock;
    input.value = val;

    // Get the previously synced qty (what server knows about)
    const previousQty = parseInt(input.dataset.prevQty || input.defaultValue) || minQty;
    input.dataset.prevQty = val;
    input.defaultValue = val;

    if (val === previousQty) {
        calculateTotal();
        return;
    }

    // Debounced server sync (reuses same debounce map)
    if (!cartDebounceTimers[cartId]) {
        activeRequests++;
    }
    updateCheckoutButtonState();

    if (cartDebounceTimers[cartId]) {
        clearTimeout(cartDebounceTimers[cartId]);
    }

    cartDebounceTimers[cartId] = setTimeout(async () => {
        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            const response = await fetch(`/shop/api/cart/update/${cartId}?qty=${val}`, {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrfToken }
            });
            const result = await response.json();
            if (result.success === false) {
                input.value = previousQty;
                input.dataset.prevQty = previousQty;
                showToast(result.message || T.update_error, 'error');
            }
            delete cartDebounceTimers[cartId];
        } catch (e) {
            input.value = previousQty;
            input.dataset.prevQty = previousQty;
            showToast(T.update_error, 'error');
        } finally {
            activeRequests--;
            updateCheckoutButtonState();
        }
    }, 500);

    calculateTotal();
}

async function removeCartItem(cartId) {
    tg.HapticFeedback.notificationOccurred('warning');
    if (!confirm(T.remove_from_cart)) return;

    const row = document.getElementById(`cart-item-${cartId}`);
    row.style.transform = 'scale(0.9) translateX(-100px)';
    row.style.opacity = '0';

    setTimeout(async () => {
        row.remove();
        calculateTotal();
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
        await fetch(`/shop/api/cart/delete/${cartId}`, {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrfToken }
        });

        const items = document.querySelectorAll('.cart-item-row');
        if (items.length === 0) location.reload();
    }, 300);
}

// Active Request Counter/Lock
let activeRequests = 0;

function updateCheckoutButtonState() {
    calculateTotal();
}

function calculateTotal() {
    let total = 0;
    const checkboxes = document.querySelectorAll('.cart-checkbox:checked');
    let count = 0;

    checkboxes.forEach(cb => {
        const cartId = cb.value;
        const price = parseInt(cb.dataset.price);
        const qty = parseInt(document.getElementById(`qty-${cartId}`).value) || 0;
        total += price * qty;
        count += 1;
    });

    const totalElem = document.getElementById('total-price');
    if (totalElem) totalElem.innerText = total.toLocaleString('ru-RU');

    const btn = document.getElementById('checkout-btn');
    if (btn) {
        if (activeRequests > 0) {
            btn.disabled = true;
            btn.classList.add('grayscale', 'opacity-70', 'cursor-wait');
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> ' + T.updating;
        } else if (count > 0) {
            btn.disabled = false;
            btn.classList.remove('grayscale', 'opacity-70', 'cursor-wait', 'opacity-50');
            btn.innerHTML = `<span>${T.checkout_btn} (${count})</span> <i class="fas fa-arrow-right text-xs"></i>`;
        } else {
            btn.disabled = true;
            btn.classList.add('grayscale', 'opacity-50');
            btn.classList.remove('opacity-70', 'cursor-wait');
            btn.innerHTML = `<span>${T.select_items}</span>`;
        }
    }
}

// --- Bottom Sheet Modal: body scroll lock + swipe-to-close ---
let _savedScrollY = 0;

function openModalLock() {
    _savedScrollY = window.scrollY;
    document.body.style.top = `-${_savedScrollY}px`;
    document.body.classList.add('modal-open');
}

function closeModalLock() {
    document.body.classList.remove('modal-open');
    document.body.style.top = '';
    window.scrollTo(0, _savedScrollY);
    // Stop all videos inside the modal so audio doesn't keep playing
    document.querySelectorAll('#product-modal video').forEach(v => { v.pause(); v.currentTime = 0; });
}

function _setupModalSheet() {
    const modal = document.getElementById('product-modal');
    const sheet = document.getElementById('modal-sheet');
    if (!modal || !sheet) return;

    let startY = 0;
    let currentY = 0;
    let isDragging = false;

    // Prevent background scroll when touching overlay area
    modal.addEventListener('touchmove', function(e) {
        if (!e.target.closest('#modal-sheet')) {
            e.preventDefault();
        }
    }, { passive: false });

    // Swipe-to-close on the sheet
    sheet.addEventListener('touchstart', function(e) {
        startY = e.touches[0].clientY;
        currentY = startY;
        isDragging = false;
    }, { passive: true });

    sheet.addEventListener('touchmove', function(e) {
        currentY = e.touches[0].clientY;
        const deltaY = currentY - startY;

        // Only start drag-to-dismiss when scrolled to top and dragging down
        if (sheet.scrollTop <= 0 && deltaY > 0) {
            if (!isDragging) {
                isDragging = true;
                sheet.style.transition = 'none';
            }
            e.preventDefault();
            sheet.style.transform = `translateY(${deltaY}px)`;
        }
    }, { passive: false });

    sheet.addEventListener('touchend', function() {
        if (!isDragging) return;

        const deltaY = currentY - startY;
        sheet.style.transition = 'transform 0.3s cubic-bezier(0.32, 0.72, 0, 1)';

        if (deltaY > 80) {
            // Dismiss: animate to bottom then hide
            sheet.style.transform = 'translateY(100%)';
            sheet.classList.remove('open');
            setTimeout(() => {
                modal.classList.add('hidden');
                sheet.style.transition = '';
                sheet.style.transform = '';
                closeModalLock();
            }, 300);
        } else {
            // Snap back
            sheet.style.transform = 'translateY(0)';
            setTimeout(() => {
                sheet.style.transition = '';
                sheet.style.transform = '';
            }, 300);
        }

        isDragging = false;
    });
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    // Initial Calc
    if (document.querySelector('.cart-checkbox')) calculateTotal();

    // Checkout Form Logic can stay similar but styled better in HTML
    (async () => {
        try {
            const res = await fetch('/shop/api/cart/count');
            const data = await res.json();
            updateCartBadge(data.count);
        } catch (e) {
            console.error(e);
        }
    })();

    // Init infinite scroll on index page
    _initInfiniteScroll();

    // Init modal sheet touch handling
    _setupModalSheet();
});

(function () {
    if (window.UNICOMAdminShareLinks) return;
    window.UNICOMAdminShareLinks = true;

    var configPromise = null;
    var toastTimer = null;

    function getConfig() {
        if (!configPromise) {
            configPromise = fetch('/admin/share-link-config', { credentials: 'same-origin' })
                .then(function (response) {
                    if (!response.ok) throw new Error('Share config unavailable');
                    return response.json();
                })
                .catch(function () {
                    return {
                        bot_username: '',
                        mini_app_short_name: '',
                        web_base_url: window.location.origin
                    };
                });
        }
        return configPromise;
    }

    function ensureToast() {
        var toast = document.getElementById('admin-copy-toast');
        if (toast) return toast;

        toast = document.createElement('div');
        toast.id = 'admin-copy-toast';
        toast.style.cssText = [
            'position:fixed',
            'top:1rem',
            'left:50%',
            'z-index:80',
            'transform:translate(-50%,-0.5rem)',
            'background:#fff',
            'color:#3E2310',
            'border:1px solid rgba(224,204,183,.65)',
            'border-radius:.85rem',
            'box-shadow:0 12px 32px -12px rgba(62,35,16,.28)',
            'padding:.7rem 1rem',
            'font-size:.8rem',
            'font-weight:800',
            'opacity:0',
            'pointer-events:none',
            'transition:opacity .18s ease, transform .18s ease'
        ].join(';');
        document.body.appendChild(toast);
        return toast;
    }

    function showToast(message) {
        var toast = ensureToast();
        toast.textContent = message;
        toast.style.opacity = '1';
        toast.style.transform = 'translate(-50%,0)';
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toast.style.opacity = '0';
            toast.style.transform = 'translate(-50%,-0.5rem)';
        }, 1600);
    }

    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }

        var input = document.createElement('textarea');
        input.value = text;
        input.setAttribute('readonly', '');
        input.style.position = 'fixed';
        input.style.top = '-1000px';
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        input.remove();
        return Promise.resolve();
    }

    function buildTelegramLink(config, payload) {
        var safePayload = encodeURIComponent(payload);
        var botUsername = (config.bot_username || '').replace(/^@+/, '');
        var miniAppShortName = (config.mini_app_short_name || '').replace(/^\/+|\/+$/g, '');

        if (botUsername && miniAppShortName) {
            return 'https://t.me/' + botUsername + '/' + miniAppShortName + '?startapp=' + safePayload;
        }
        if (botUsername) {
            return 'https://t.me/' + botUsername + '?startapp=' + safePayload;
        }

        var baseUrl = (config.web_base_url || window.location.origin).replace(/\/+$/, '');
        return baseUrl + '/shop?tgWebAppStartParam=' + safePayload;
    }

    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-copy-payload]');
        if (!button) return;

        event.preventDefault();
        event.stopPropagation();

        var payload = button.getAttribute('data-copy-payload');
        if (!payload) return;

        var icon = button.querySelector('i');
        var previousIcon = icon ? icon.className : '';
        var previousTitle = button.getAttribute('title') || '';

        getConfig()
            .then(function (config) {
                return copyText(buildTelegramLink(config, payload));
            })
            .then(function () {
                if (icon) icon.className = 'fas fa-check';
                button.setAttribute('title', 'Скопировано');
                showToast(button.getAttribute('data-copy-success') || 'Ссылка скопирована');
            })
            .catch(function (error) {
                showToast('Не удалось скопировать ссылку');
                console.error('Copy link failed', error);
            })
            .finally(function () {
                setTimeout(function () {
                    if (icon && previousIcon) icon.className = previousIcon;
                    if (previousTitle) button.setAttribute('title', previousTitle);
                }, 1400);
            });
    });
})();

(function () {
    const SELECTOR = 'input[type="file"][data-admin-image-cropper]';
    const bypassInputs = new WeakSet();
    let modal = null;
    let activeCleanup = null;

    function injectStyles() {
        if (document.getElementById('admin-image-cropper-styles')) return;
        const style = document.createElement('style');
        style.id = 'admin-image-cropper-styles';
        style.textContent = `
            .admin-cropper-modal{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;color:#3E2310}
            .admin-cropper-modal.hidden{display:none}
            .admin-cropper-backdrop{position:absolute;inset:0;background:rgba(42,24,11,.62);backdrop-filter:blur(6px)}
            .admin-cropper-dialog{position:relative;width:min(720px,100%);max-height:calc(100vh - 32px);display:flex;flex-direction:column;overflow:hidden;background:#fff;border:1px solid rgba(224,204,183,.7);border-radius:24px;box-shadow:0 26px 70px -24px rgba(42,24,11,.55)}
            .admin-cropper-header,.admin-cropper-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-color:rgba(224,204,183,.65)}
            .admin-cropper-header{border-bottom-width:1px}
            .admin-cropper-footer{border-top-width:1px;background:#fff}
            .admin-cropper-title{min-width:0;font-weight:800;font-size:15px;line-height:1.2}
            .admin-cropper-subtitle{margin-top:3px;color:#8C735F;font-size:11px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:560px}
            .admin-cropper-icon-btn{width:38px;height:38px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;border-radius:12px;background:#EFE6DB;color:#6B3F1E;transition:background .18s,color .18s}
            .admin-cropper-icon-btn:hover{background:#6B3F1E;color:#fff}
            .admin-cropper-body{padding:16px;background:#F9F4EF;overflow:auto}
            .admin-cropper-stage-wrap{display:flex;align-items:center;justify-content:center;min-height:220px}
            .admin-cropper-stage{position:relative;overflow:hidden;background:#2A180B;border-radius:18px;box-shadow:0 18px 44px -24px rgba(42,24,11,.72);touch-action:none;cursor:grab}
            .admin-cropper-stage:active{cursor:grabbing}
            .admin-cropper-stage::after{content:"";position:absolute;inset:0;border:2px solid rgba(255,255,255,.9);border-radius:18px;pointer-events:none;box-shadow:inset 0 0 0 1px rgba(42,24,11,.22)}
            .admin-cropper-media{position:absolute;top:0;left:0;max-width:none;max-height:none;user-select:none;-webkit-user-drag:none;will-change:transform,width,height}
            .admin-cropper-media.hidden{display:none}
            .admin-cropper-tools{display:flex;align-items:center;gap:10px;margin-top:14px}
            .admin-cropper-range{flex:1;accent-color:#6B3F1E}
            .admin-cropper-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:12px;font-weight:800;font-size:13px;padding:10px 14px;transition:background .18s,color .18s,opacity .18s}
            .admin-cropper-btn-secondary{background:#EFE6DB;color:#3E2310}
            .admin-cropper-btn-secondary:hover{background:#E0CCB7}
            .admin-cropper-btn-primary{background:#6B3F1E;color:#fff;box-shadow:0 8px 24px -10px rgba(107,63,30,.65)}
            .admin-cropper-btn-primary:hover{background:#543116}
            .admin-cropper-btn:disabled{opacity:.65;cursor:not-allowed}
            @media (max-width:520px){
                .admin-cropper-modal{padding:0;align-items:flex-end}
                .admin-cropper-dialog{width:100%;max-height:94vh;border-radius:24px 24px 0 0}
                .admin-cropper-footer{flex-wrap:wrap}
                .admin-cropper-btn{flex:1}
            }
        `;
        document.head.appendChild(style);
    }

    function ensureModal() {
        if (modal) return modal;
        injectStyles();
        modal = document.createElement('div');
        modal.className = 'admin-cropper-modal hidden';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.innerHTML = `
            <div class="admin-cropper-backdrop" data-cropper-cancel></div>
            <div class="admin-cropper-dialog">
                <div class="admin-cropper-header">
                    <div class="min-w-0">
                        <div class="admin-cropper-title" data-cropper-title>Кадрирование фото</div>
                        <div class="admin-cropper-subtitle" data-cropper-subtitle></div>
                    </div>
                    <button type="button" class="admin-cropper-icon-btn" data-cropper-cancel aria-label="Закрыть">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="admin-cropper-body">
                    <div class="admin-cropper-stage-wrap">
                        <div class="admin-cropper-stage" data-cropper-stage>
                            <img class="admin-cropper-media" data-cropper-img alt="">
                            <video class="admin-cropper-media hidden" data-cropper-video muted playsinline loop></video>
                        </div>
                    </div>
                    <div class="admin-cropper-tools">
                        <button type="button" class="admin-cropper-icon-btn" data-cropper-zoom-out aria-label="Уменьшить">
                            <i class="fas fa-search-minus"></i>
                        </button>
                        <input class="admin-cropper-range" data-cropper-range type="range" min="100" max="300" value="100" step="1" aria-label="Масштаб">
                        <button type="button" class="admin-cropper-icon-btn" data-cropper-zoom-in aria-label="Увеличить">
                            <i class="fas fa-search-plus"></i>
                        </button>
                        <button type="button" class="admin-cropper-icon-btn" data-cropper-reset aria-label="Сбросить">
                            <i class="fas fa-rotate-left"></i>
                        </button>
                    </div>
                </div>
                <div class="admin-cropper-footer">
                    <button type="button" class="admin-cropper-btn admin-cropper-btn-secondary" data-cropper-cancel>Отмена</button>
                    <button type="button" class="admin-cropper-btn admin-cropper-btn-primary" data-cropper-apply>
                        <i class="fas fa-check"></i> Применить
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        return modal;
    }

    function fileExt(file) {
        return (file && file.name && file.name.includes('.'))
            ? file.name.split('.').pop().toLowerCase()
            : '';
    }

    function isGifFile(file) {
        return fileExt(file) === 'gif' || file.type === 'image/gif';
    }

    function isImageFile(file) {
        if (!file || !file.name) return false;
        if (file.type && file.type.startsWith('image/') && file.type !== 'image/svg+xml') return true;
        return /\.(jpe?g|png|gif|bmp|webp|tiff?|heic)$/i.test(file.name);
    }

    function isVideoFile(file) {
        if (!file || !file.name) return false;
        if (file.type && file.type.startsWith('video/')) return true;
        return /\.(mp4|webm|mov|avi)$/i.test(file.name);
    }

    function preservesAnimation(input, file) {
        return input.dataset.cropPreserveAnimation === 'true' && (isGifFile(file) || isVideoFile(file));
    }

    function isCroppableFile(input, file) {
        return isImageFile(file) || preservesAnimation(input, file);
    }

    function readSettings(input) {
        const width = parseInt(input.dataset.cropWidth || '', 10);
        const height = parseInt(input.dataset.cropHeight || '', 10);
        const explicitAspect = parseFloat(input.dataset.cropAspect || '');
        const aspect = explicitAspect || (width && height ? width / height : 1);
        const outputWidth = width || 1200;
        const outputHeight = height || Math.round(outputWidth / aspect);
        return {
            aspect,
            outputWidth,
            outputHeight,
            title: input.dataset.cropTitle || 'Кадрирование фото',
            preserveAnimation: input.dataset.cropPreserveAnimation === 'true',
        };
    }

    function lockBody(locked) {
        document.documentElement.style.overflow = locked ? 'hidden' : '';
        document.body.style.overflow = locked ? 'hidden' : '';
    }

    function setFiles(input, files) {
        const dt = new DataTransfer();
        files.forEach((file) => dt.items.add(file));
        input.files = dt.files;
    }

    function croppedFileName(name) {
        const clean = (name || 'image').replace(/\.[^/.]+$/, '');
        return `${clean}-crop.jpg`;
    }

    function cropFieldNames(input) {
        const base = input.name || 'image';
        return {
            x: `${base}_crop_x`,
            y: `${base}_crop_y`,
            width: `${base}_crop_width`,
            height: `${base}_crop_height`,
            outputWidth: `${base}_crop_output_width`,
            outputHeight: `${base}_crop_output_height`,
        };
    }

    function ensureHiddenField(input, name) {
        const form = input.form;
        if (!form) return null;
        let field = form.querySelector(`input[type="hidden"][name="${name}"]`);
        if (!field) {
            field = document.createElement('input');
            field.type = 'hidden';
            field.name = name;
            input.insertAdjacentElement('afterend', field);
        }
        return field;
    }

    function setCropFields(input, crop) {
        if (!crop) {
            clearCropFields(input);
            return;
        }
        const names = cropFieldNames(input);
        Object.keys(names).forEach((key) => {
            const field = ensureHiddenField(input, names[key]);
            if (field) field.value = crop[key] !== undefined ? String(crop[key]) : '';
        });
    }

    function clearCropFields(input) {
        const form = input.form;
        if (!form) return;
        const names = cropFieldNames(input);
        Object.keys(names).forEach((key) => {
            const field = form.querySelector(`input[type="hidden"][name="${names[key]}"]`);
            if (field) field.remove();
        });
    }

    function canvasToBlob(canvas) {
        return new Promise((resolve) => {
            if (canvas.toBlob) {
                canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.92);
                return;
            }
            const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
            const parts = dataUrl.split(',');
            const binary = atob(parts[1]);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
            resolve(new Blob([bytes], { type: 'image/jpeg' }));
        });
    }

    function openCropper(file, settings) {
        return new Promise((resolve) => {
            const root = ensureModal();
            const stage = root.querySelector('[data-cropper-stage]');
            const image = root.querySelector('[data-cropper-img]');
            const video = root.querySelector('[data-cropper-video]');
            const range = root.querySelector('[data-cropper-range]');
            const applyBtn = root.querySelector('[data-cropper-apply]');
            const title = root.querySelector('[data-cropper-title]');
            const subtitle = root.querySelector('[data-cropper-subtitle]');
            const url = URL.createObjectURL(file);
            const keepAnimated = settings.preserveAnimation && (isGifFile(file) || isVideoFile(file));
            const useVideo = keepAnimated && isVideoFile(file);
            const media = useVideo ? video : image;

            let naturalWidth = 0;
            let naturalHeight = 0;
            let stageWidth = 0;
            let stageHeight = 0;
            let minScale = 1;
            let scale = 1;
            let x = 0;
            let y = 0;
            let drag = null;
            let resolved = false;

            function cleanup() {
                if (activeCleanup) {
                    activeCleanup();
                    activeCleanup = null;
                }
                URL.revokeObjectURL(url);
                image.removeAttribute('src');
                video.pause();
                video.removeAttribute('src');
                video.load();
                image.classList.add('hidden');
                video.classList.add('hidden');
                root.classList.add('hidden');
                lockBody(false);
            }

            function finish(value) {
                if (resolved) return;
                resolved = true;
                cleanup();
                resolve(value);
            }

            function addListener(target, type, handler, options) {
                target.addEventListener(type, handler, options);
                return () => target.removeEventListener(type, handler, options);
            }

            const listeners = [];
            activeCleanup = function () {
                listeners.splice(0).forEach((remove) => remove());
            };

            function sizeStage() {
                const maxWidth = Math.max(260, Math.min(window.innerWidth - 40, 620));
                const maxHeight = Math.max(220, Math.min(window.innerHeight - 280, 560));
                let width = maxWidth;
                let height = width / settings.aspect;
                if (height > maxHeight) {
                    height = maxHeight;
                    width = height * settings.aspect;
                }
                stage.style.width = `${Math.round(width)}px`;
                stage.style.height = `${Math.round(height)}px`;
                stageWidth = stage.clientWidth;
                stageHeight = stage.clientHeight;
            }

            function clampPosition() {
                const displayWidth = naturalWidth * scale;
                const displayHeight = naturalHeight * scale;
                if (displayWidth <= stageWidth) {
                    x = (stageWidth - displayWidth) / 2;
                } else {
                    x = Math.min(0, Math.max(stageWidth - displayWidth, x));
                }
                if (displayHeight <= stageHeight) {
                    y = (stageHeight - displayHeight) / 2;
                } else {
                    y = Math.min(0, Math.max(stageHeight - displayHeight, y));
                }
            }

            function render() {
                clampPosition();
                media.style.width = `${naturalWidth * scale}px`;
                media.style.height = `${naturalHeight * scale}px`;
                media.style.transform = `translate(${x}px, ${y}px)`;
            }

            function setZoomFactor(factor, centerX, centerY) {
                const previousScale = scale;
                const pointX = (centerX - x) / previousScale;
                const pointY = (centerY - y) / previousScale;
                const nextFactor = Math.max(1, Math.min(3, factor));
                scale = minScale * nextFactor;
                x = centerX - pointX * scale;
                y = centerY - pointY * scale;
                range.value = String(Math.round(nextFactor * 100));
                render();
            }

            function resetImage() {
                sizeStage();
                minScale = Math.max(stageWidth / naturalWidth, stageHeight / naturalHeight);
                scale = minScale;
                x = (stageWidth - naturalWidth * scale) / 2;
                y = (stageHeight - naturalHeight * scale) / 2;
                range.value = '100';
                render();
            }

            function clientPoint(event) {
                const rect = stage.getBoundingClientRect();
                return {
                    x: event.clientX - rect.left,
                    y: event.clientY - rect.top,
                };
            }

            function onPointerDown(event) {
                if (event.button !== undefined && event.button !== 0) return;
                event.preventDefault();
                drag = {
                    pointerId: event.pointerId,
                    startClientX: event.clientX,
                    startClientY: event.clientY,
                    startX: x,
                    startY: y,
                };
                stage.setPointerCapture(event.pointerId);
            }

            function onPointerMove(event) {
                if (!drag || drag.pointerId !== event.pointerId) return;
                event.preventDefault();
                x = drag.startX + event.clientX - drag.startClientX;
                y = drag.startY + event.clientY - drag.startClientY;
                render();
            }

            function onPointerUp(event) {
                if (!drag || drag.pointerId !== event.pointerId) return;
                drag = null;
                try {
                    stage.releasePointerCapture(event.pointerId);
                } catch (err) {}
            }

            function cropPayload() {
                const sx = Math.max(0, -x / scale);
                const sy = Math.max(0, -y / scale);
                return {
                    x: Math.round(sx),
                    y: Math.round(sy),
                    width: Math.round(Math.min(naturalWidth - sx, stageWidth / scale)),
                    height: Math.round(Math.min(naturalHeight - sy, stageHeight / scale)),
                    outputWidth: settings.outputWidth,
                    outputHeight: settings.outputHeight,
                };
            }

            async function applyCrop() {
                applyBtn.disabled = true;
                applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Готовим...';
                try {
                    if (keepAnimated) {
                        finish({ file, crop: cropPayload() });
                        return;
                    }
                    const canvas = document.createElement('canvas');
                    canvas.width = settings.outputWidth;
                    canvas.height = settings.outputHeight;
                    const ctx = canvas.getContext('2d', { alpha: false });
                    ctx.fillStyle = '#ffffff';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.imageSmoothingEnabled = true;
                    ctx.imageSmoothingQuality = 'high';
                    const sx = -x / scale;
                    const sy = -y / scale;
                    const sw = stageWidth / scale;
                    const sh = stageHeight / scale;
                    ctx.drawImage(media, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
                    const blob = await canvasToBlob(canvas);
                    if (!blob) throw new Error('empty_blob');
                    finish({
                        file: new File([blob], croppedFileName(file.name), {
                            type: 'image/jpeg',
                            lastModified: Date.now(),
                        }),
                    });
                } catch (err) {
                    console.error('Image crop failed', err);
                    alert('Не удалось кадрировать изображение. Попробуйте другой файл.');
                    applyBtn.disabled = false;
                    applyBtn.innerHTML = '<i class="fas fa-check"></i> Применить';
                }
            }

            title.textContent = settings.title;
            subtitle.textContent = file.name;
            range.value = '100';
            applyBtn.disabled = false;
            applyBtn.innerHTML = '<i class="fas fa-check"></i> Применить';
            root.classList.remove('hidden');
            lockBody(true);
            image.classList.toggle('hidden', useVideo);
            video.classList.toggle('hidden', !useVideo);

            if (useVideo) {
                listeners.push(addListener(video, 'loadedmetadata', function () {
                    naturalWidth = video.videoWidth;
                    naturalHeight = video.videoHeight;
                    if (!naturalWidth || !naturalHeight) {
                        alert('Не удалось открыть видео. Попробуйте другой файл.');
                        finish(null);
                        return;
                    }
                    resetImage();
                    video.currentTime = Math.min(0.15, video.duration || 0.15);
                    video.play().catch(function () {});
                }, { once: true }));
                listeners.push(addListener(video, 'error', function () {
                    alert('Не удалось открыть видео. Попробуйте другой файл.');
                    finish(null);
                }, { once: true }));
            } else {
                listeners.push(addListener(image, 'load', function () {
                    naturalWidth = image.naturalWidth;
                    naturalHeight = image.naturalHeight;
                    if (!naturalWidth || !naturalHeight) {
                        alert('Не удалось открыть изображение. Попробуйте другой файл.');
                        finish(null);
                        return;
                    }
                    resetImage();
                }, { once: true }));

                listeners.push(addListener(image, 'error', function () {
                    alert('Не удалось открыть изображение. Попробуйте другой файл.');
                    finish(null);
                }, { once: true }));
            }

            listeners.push(addListener(stage, 'pointerdown', onPointerDown));
            listeners.push(addListener(stage, 'pointermove', onPointerMove));
            listeners.push(addListener(stage, 'pointerup', onPointerUp));
            listeners.push(addListener(stage, 'pointercancel', onPointerUp));
            listeners.push(addListener(range, 'input', function () {
                setZoomFactor(Number(range.value) / 100, stageWidth / 2, stageHeight / 2);
            }));
            listeners.push(addListener(root.querySelector('[data-cropper-zoom-out]'), 'click', function () {
                setZoomFactor(Number(range.value) / 100 - 0.1, stageWidth / 2, stageHeight / 2);
            }));
            listeners.push(addListener(root.querySelector('[data-cropper-zoom-in]'), 'click', function () {
                setZoomFactor(Number(range.value) / 100 + 0.1, stageWidth / 2, stageHeight / 2);
            }));
            listeners.push(addListener(root.querySelector('[data-cropper-reset]'), 'click', resetImage));
            listeners.push(addListener(applyBtn, 'click', applyCrop));
            root.querySelectorAll('[data-cropper-cancel]').forEach((button) => {
                listeners.push(addListener(button, 'click', function () { finish(null); }));
            });
            listeners.push(addListener(stage, 'wheel', function (event) {
                event.preventDefault();
                const point = clientPoint(event);
                const delta = event.deltaY < 0 ? 0.08 : -0.08;
                setZoomFactor(Number(range.value) / 100 + delta, point.x, point.y);
            }, { passive: false }));
            listeners.push(addListener(window, 'resize', resetImage));
            listeners.push(addListener(document, 'keydown', function (event) {
                if (event.key === 'Escape') finish(null);
            }));

            if (useVideo) {
                video.src = url;
                video.load();
            } else {
                image.src = url;
            }
        });
    }

    document.addEventListener('change', async function (event) {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.matches(SELECTOR)) return;
        if (bypassInputs.has(input)) {
            bypassInputs.delete(input);
            return;
        }

        const files = Array.from(input.files || []);
        if (!files.some((file) => isCroppableFile(input, file))) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        const settings = readSettings(input);
        const nextFiles = [];
        let animatedCrop = null;
        input.disabled = true;
        clearCropFields(input);

        try {
            for (const file of files) {
                if (!isCroppableFile(input, file)) {
                    nextFiles.push(file);
                    continue;
                }
                const cropped = await openCropper(file, settings);
                if (cropped && cropped.file) {
                    nextFiles.push(cropped.file);
                    if (cropped.crop) animatedCrop = cropped.crop;
                }
            }
            if (animatedCrop) setCropFields(input, animatedCrop);
            setFiles(input, nextFiles);
        } finally {
            input.disabled = false;
            bypassInputs.add(input);
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }, true);
})();

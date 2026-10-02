import { app } from "../../scripts/app.js";

// Fasst ratio_width/ratio_height zu einer Zeile "W <-> H" mit Swap-Button
// zusammen und zeigt darüber live die berechnete Auflösung an.
app.registerExtension({
    name: "FreeResolutionSelector.SideBySide",
    async nodeCreated(node) {
        if (node.comfyClass !== "FreeResolutionSelector") return;

        const widthWidget = node.widgets?.find((w) => w.name === "ratio_width");
        const heightWidget = node.widgets?.find((w) => w.name === "ratio_height");
        const megapixelWidget = node.widgets?.find((w) => w.name === "megapixel");
        const multipleWidget = node.widgets?.find((w) => w.name === "multiple");
        if (!widthWidget || !heightWidget || !megapixelWidget || !multipleWidget) return;

        // Original-Widgets komplett aus dem Zeichnen UND aus der
        // Maus-Interaktion nehmen - "disabled" verhindert, dass Klicks auf
        // ihre (eigentlich unsichtbare) Fläche noch etwas verändern.
        widthWidget.computeSize = () => [0, 0];
        heightWidget.computeSize = () => [0, 0];
        widthWidget.hidden = true;
        heightWidget.hidden = true;
        widthWidget.disabled = true;
        heightWidget.disabled = true;

        const container = document.createElement("div");
        container.style.display = "flex";
        container.style.flexDirection = "column";
        container.style.gap = "3px";
        container.style.padding = "0 5px";
        container.style.width = "100%";
        container.style.boxSizing = "border-box";

        const previewLabel = document.createElement("div");
        previewLabel.style.fontSize = "11px";
        previewLabel.style.opacity = "0.85";
        previewLabel.style.textAlign = "center";
        previewLabel.style.color = "#9fd";
        previewLabel.style.padding = "0";

        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.alignItems = "center";
        row.style.gap = "6px";
        row.style.width = "100%";

        const roundToMultiple = (x, m) => Math.max(m, Math.round(x / m) * m);

        const updatePreview = () => {
            const rw = parseFloat(widthWidget.value) || 1;
            const rh = parseFloat(heightWidget.value) || 1;
            const mp = parseFloat(megapixelWidget.value) || 1;
            const mult = parseInt(multipleWidget.value, 10) || 8;

            const targetArea = mp * 1_000_000;
            const scale = Math.sqrt(targetArea / (rw * rh));

            const width = roundToMultiple(rw * scale, mult);
            const height = roundToMultiple(rh * scale, mult);
            const actualMp = Math.round(((width * height) / 1_000_000) * 100) / 100;

            previewLabel.textContent = `${width} x ${height}  (${actualMp} MP)`;
        };

        const makeInput = (widget) => {
            const input = document.createElement("input");
            input.type = "number";
            input.step = "1";
            input.min = "1";
            input.value = widget.value;
            input.style.width = "100%";
            input.style.minWidth = "0";
            input.style.background = "#1a1a1a";
            input.style.color = "#fff";
            input.style.border = "1px solid #444";
            input.style.borderRadius = "4px";
            input.style.padding = "2px 4px";
            input.style.fontSize = "12px";
            input.style.textAlign = "center";

            const commit = () => {
                const v = parseInt(input.value, 10);
                if (!isNaN(v)) {
                    widget.value = v;
                }
                updatePreview();
            };
            input.addEventListener("input", commit);
            input.addEventListener("change", commit);

            return input;
        };

        const widthWrap = document.createElement("div");
        widthWrap.style.flex = "1";
        widthWrap.style.minWidth = "0";
        const widthInput = makeInput(widthWidget);
        widthWrap.appendChild(widthInput);

        const heightWrap = document.createElement("div");
        heightWrap.style.flex = "1";
        heightWrap.style.minWidth = "0";
        const heightInput = makeInput(heightWidget);
        heightWrap.appendChild(heightInput);

        const swapBtn = document.createElement("button");
        swapBtn.textContent = "\u2194"; // <->
        swapBtn.title = "Swap width and height";
        swapBtn.style.flexShrink = "0";
        swapBtn.style.width = "22px";
        swapBtn.style.height = "22px";
        swapBtn.style.lineHeight = "1";
        swapBtn.style.background = "#2a2a2a";
        swapBtn.style.color = "#ccc";
        swapBtn.style.border = "1px solid #555";
        swapBtn.style.borderRadius = "4px";
        swapBtn.style.cursor = "pointer";
        swapBtn.style.padding = "0";

        swapBtn.addEventListener("click", () => {
            const w = widthWidget.value;
            const h = heightWidget.value;
            widthWidget.value = h;
            heightWidget.value = w;
            widthInput.value = h;
            heightInput.value = w;
            updatePreview();
            node.setDirtyCanvas(true, true);
        });

        row.appendChild(widthWrap);
        row.appendChild(swapBtn);
        row.appendChild(heightWrap);

        container.appendChild(previewLabel);
        container.appendChild(row);

        // megapixel/multiple ändern sich über ihre eigenen Standard-Widgets;
        // deren callback einmalig umschließen (Guard verhindert Mehrfach-Wrap).
        const wrapCallback = (widget) => {
            if (widget._freeResPreviewWrapped) return;
            widget._freeResPreviewWrapped = true;
            const original = widget.callback;
            widget.callback = function (...args) {
                const r = original ? original.apply(this, args) : undefined;
                updatePreview();
                return r;
            };
        };
        wrapCallback(megapixelWidget);
        wrapCallback(multipleWidget);

        const domWidget = node.addDOMWidget("ratio_preview_row", "custom", container, {
            serialize: false,
            hideOnZoom: false,
        });

        // Feste, kompakte Höhe statt Strecken auf verfügbaren Platz -
        // sonst entsteht genau hier der Leerraum, statt am Node-Ende.
        domWidget.computeSize = () => [0, 50];

        // Sichtbare Zeile ganz nach oben - die ausgeblendeten Original-
        // Widgets stehen dank Python-Reihenfolge bereits am Ende.
        const domIdx = node.widgets.indexOf(domWidget);
        if (domIdx > -1) {
            node.widgets.splice(domIdx, 1);
            node.widgets.unshift(domWidget);
        }

        updatePreview();

        // Nach dem Laden eines gespeicherten Workflows schreibt ComfyUI die
        // echten Werte erst NACH nodeCreated in die Widgets (configure()).
        const originalOnConfigure = node.onConfigure;
        node.onConfigure = function (...args) {
            const r = originalOnConfigure ? originalOnConfigure.apply(this, args) : undefined;
            widthInput.value = widthWidget.value;
            heightInput.value = heightWidget.value;
            updatePreview();
            return r;
        };
    },
});
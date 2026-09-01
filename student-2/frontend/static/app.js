document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-tab-target]");
    const panels = document.querySelectorAll(".tab-panel");

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.dataset.tabTarget;

            buttons.forEach((item) => {
                const active = item === button;
                item.classList.toggle("is-active", active);
                item.setAttribute("aria-selected", String(active));
            });

            panels.forEach((panel) => {
                const active = panel.id === targetId;
                panel.classList.toggle("is-active", active);
                panel.hidden = !active;
            });
        });
    });

    if (!window.htmx) {
        const banner = document.createElement("div");
        banner.className = "notice notice--error global-notice";
        banner.textContent = "HTMX could not be loaded. Check the internet connection before the showcase.";
        document.body.prepend(banner);
    }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
    const notice = event.detail.target.querySelector?.(".notice");
    if (notice) {
        notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
});

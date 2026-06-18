/**
 * EstateAI - Client Side Interactivity
 */

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initToasts();
});

/**
 * Theme Toggle Logic
 */
function initTheme() {
    const themeToggleBtn = document.getElementById("theme-toggle");
    if (!themeToggleBtn) return;

    // Get current theme from localStorage or default to dark
    let currentTheme = localStorage.getItem("theme") || "dark";
    
    // Set active theme
    document.documentElement.setAttribute("data-theme", currentTheme);

    // Event listener for toggle click
    themeToggleBtn.addEventListener("click", () => {
        currentTheme = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        
        // Apply theme attribute
        document.documentElement.setAttribute("data-theme", currentTheme);
        
        // Save choice
        localStorage.setItem("theme", currentTheme);

        // Update charts if present
        if (typeof Chart !== "undefined") {
            updateChartsTheme(currentTheme);
        }
    });
}

/**
 * Automatically update Chart.js theme variables when changing mode
 */
function updateChartsTheme(theme) {
    const isDark = theme === "dark";
    const textThemeColor = isDark ? "#94a3b8" : "#475569";
    const gridThemeColor = isDark ? "rgba(255, 255, 255, 0.06)" : "rgba(15, 23, 42, 0.06)";

    Chart.helpers.each(Chart.instances, (chart) => {
        // Update scales configuration
        if (chart.options.scales) {
            if (chart.options.scales.x && chart.options.scales.x.ticks) {
                chart.options.scales.x.ticks.color = textThemeColor;
            }
            if (chart.options.scales.y) {
                if (chart.options.scales.y.ticks) chart.options.scales.y.ticks.color = textThemeColor;
                if (chart.options.scales.y.grid) chart.options.scales.y.grid.color = gridThemeColor;
            }
        }
        // Update legend options
        if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
            chart.options.plugins.legend.labels.color = textThemeColor;
        }
        // Update tooltip options
        if (chart.options.plugins && chart.options.plugins.tooltip) {
            chart.options.plugins.tooltip.backgroundColor = isDark ? '#0c0f22' : '#ffffff';
            chart.options.plugins.tooltip.titleColor = isDark ? '#ffffff' : '#0f172a';
            chart.options.plugins.tooltip.bodyColor = isDark ? '#f8fafc' : '#475569';
        }
        chart.update();
    });
}

/**
 * Toast notifications auto-dismiss
 */
function initToasts() {
    const toasts = document.querySelectorAll(".toast");
    toasts.forEach((toast) => {
        // Auto remove toast after 5 seconds
        setTimeout(() => {
            toast.style.transition = "opacity 0.5s ease, transform 0.5s ease";
            toast.style.opacity = "0";
            toast.style.transform = "translateX(100px)";
            setTimeout(() => {
                toast.remove();
            }, 500);
        }, 5000);
    });
}

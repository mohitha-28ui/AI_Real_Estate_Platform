/**
 * EstateAI - Client Side Interactivity
 */

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initToasts();
    initCarousel();
    initStarLabels();
    initPDFLinks();
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

/**
 * Landing Page Reviews Carousel
 */
function initCarousel() {
    const track = document.getElementById("carousel-track");
    const slides = document.querySelectorAll(".carousel-slide");
    const dotsContainer = document.getElementById("carousel-dots");
    if (!track || slides.length === 0) return;

    let currentIndex = 0;
    const totalSlides = slides.length;
    let autoPlayInterval;

    // Create dot indicators
    slides.forEach((_, index) => {
        const dot = document.createElement("div");
        dot.classList.add("carousel-dot");
        if (index === 0) dot.classList.add("active");
        dot.addEventListener("click", () => {
            goToSlide(index);
            resetAutoPlay();
        });
        dotsContainer.appendChild(dot);
    });

    const dots = document.querySelectorAll(".carousel-dot");

    function goToSlide(index) {
        currentIndex = index;
        track.style.transform = `translateX(-${currentIndex * 100}%)`;
        
        // Update dots
        dots.forEach((dot, idx) => {
            if (idx === currentIndex) {
                dot.classList.add("active");
            } else {
                dot.classList.remove("active");
            }
        });
    }

    function nextSlide() {
        let nextIndex = (currentIndex + 1) % totalSlides;
        goToSlide(nextIndex);
    }

    function startAutoPlay() {
        autoPlayInterval = setInterval(nextSlide, 5000); // Shift slide every 5 seconds
    }

    function resetAutoPlay() {
        clearInterval(autoPlayInterval);
        startAutoPlay();
    }

    // Start AutoPlay
    startAutoPlay();
}

/**
 * Custom text indicator for Star selection (Optional enhancement)
 */
function initStarLabels() {
    const starsInputs = document.querySelectorAll(".star-rating-selector input");
    const starValText = document.getElementById("star-val-text");
    if (starsInputs.length === 0 || !starValText) return;

    const ratingsMap = {
        "1": "1 Star - Poor experience",
        "2": "2 Stars - Disappointing",
        "3": "3 Stars - Average platform",
        "4": "4 Stars - Good and clean UI",
        "5": "5 Stars - Amazing prediction platform!"
    };

    starsInputs.forEach((input) => {
        input.addEventListener("change", (e) => {
            const val = e.target.value;
            starValText.innerText = ratingsMap[val] || "";
            starValText.style.color = "var(--color-warning)";
        });
    });
}

/**
 * Prevent duplicate PDF exports and show loading state
 */
function initPDFLinks() {
    document.querySelectorAll('a[href*="/pdf"]').forEach(link => {
        link.addEventListener('click', function(e) {
            if (this.classList.contains('disabled')) {
                e.preventDefault();
                return;
            }
            this.classList.add('disabled');
            const originalHTML = this.innerHTML;
            this.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';
            
            // Re-enable after 4 seconds
            setTimeout(() => {
                this.classList.remove('disabled');
                this.innerHTML = originalHTML;
            }, 4000);
        });
    });
}

/**
 * Global dynamic toast notification alert
 */
function showToast(message, category = "info") {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${category}`;
    
    let iconClass = "fa-circle-info";
    if (category === "success") iconClass = "fa-circle-check";
    else if (category === "danger") iconClass = "fa-circle-exclamation";

    toast.innerHTML = `
        <div class="toast-content">
            <i class="fa-solid ${iconClass} toast-icon"></i>
            <span class="toast-message">${message}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);

    // Auto remove after 5 seconds
    setTimeout(() => {
        toast.style.transition = "opacity 0.5s ease, transform 0.5s ease";
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100px)";
        setTimeout(() => {
            toast.remove();
        }, 500);
    }, 5000);
}

document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    btn.addEventListener("click", function () {
        const htmlTag = document.documentElement;
        const currentTheme = htmlTag.getAttribute("data-bs-theme");
        htmlTag.setAttribute("data-bs-theme", currentTheme === "light" ? "dark" : "light");
    });
});
